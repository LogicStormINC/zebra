"""Atomic temporary text transport. Redis time owns expiry checks."""

SNAPSHOT = """
local revision=redis.call('HGET',KEYS[1],'revision')
if not revision then
 revision=ARGV[1]
 redis.call('HSET',KEYS[1],'revision',revision)
 -- Reservation carries no authority; bounded metadata also detects absent-state ABA.
 redis.call('PEXPIRE',KEYS[1],3600000)
end
return {revision}
"""

ACTIVATE = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local gen,epoch,token,owner,expiry,maximum,renew,expected,revision=unpack(ARGV)
if redis.call('HGET',KEYS[1],'revision')~=expected then return {'changed'} end
local function less(a,b)
 if string.len(a)~=string.len(b) then return string.len(a)<string.len(b) end
 return a<b
end
expiry=tonumber(expiry); maximum=tonumber(maximum)
if expiry<=now or expiry>now+30000 or maximum<=now then return {'expired'} end
if ARGV[10] and string.len(ARGV[10])>8192 then return {'descriptor_size'} end
local old=redis.call('HGET',KEYS[1],'generation')
if renew=='1' and not old then return {'lost'} end
if redis.call('HEXISTS',KEYS[1],'retired:'..gen)==1 then return {'retired'} end
if old then
 local oldepoch=redis.call('HGET',KEYS[1],'epoch')
 local oldtoken=redis.call('HGET',KEYS[1],'token')
 if oldepoch==epoch and less(token,oldtoken) then return {'fence'} end
 if oldepoch==epoch and token==oldtoken and
 redis.call('HGET',KEYS[1],'owner')~=owner then
  return {'fence'}
 end
 if old==gen then
  if redis.call('HGET',KEYS[1],'closed')=='1' then return {'retired'} end
  if oldepoch~=epoch or token~=oldtoken then return {'fence'} end
  maximum=tonumber(redis.call('HGET',KEYS[1],'maximum'))
 else
  if tonumber(redis.call('HGET',KEYS[1],'generations') or '1')>=256 then return {'capacity'} end
  redis.call('HINCRBY',KEYS[1],'generations',1)
  redis.call('HSET',KEYS[1],'retired:'..old,'1')
 end
end
if not old or old~=gen then
 redis.call('HSET',KEYS[1],'rows','0','bytes','0','last','-1','cursor','0-0')
end
expiry=math.min(expiry,maximum)
if expiry<=now then return {'expired'} end
redis.call('HSET',KEYS[1],'generation',gen,'epoch',epoch,'token',token,
 'owner',owner,'expiry',expiry,'maximum',maximum,'closed','0','revision',revision)
if ARGV[10] and ARGV[10]~='' then
 redis.call('HSET',KEYS[1],'descriptor',ARGV[10])
end
if old~=gen then redis.call('XADD',KEYS[4],'MAXLEN','~',256,'*','generation',gen) end
-- Fixed lane expiry never slides on renew/publish/read.
local laneend=redis.call('HGET',KEYS[1],'laneend')
if not laneend then laneend=maximum; redis.call('HSET',KEYS[1],'laneend',laneend) end
redis.call('PEXPIREAT',KEYS[1],laneend)
redis.call('PEXPIREAT',KEYS[4],laneend)
return {'ok'}
"""

PUBLISH = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local gen,epoch,token,owner,offset,body,bytecap,rowcap,digest=unpack(ARGV)
if redis.call('HGET',KEYS[1],'generation')~=gen or
 redis.call('HGET',KEYS[1],'epoch')~=epoch or
 redis.call('HGET',KEYS[1],'token')~=token or
 redis.call('HGET',KEYS[1],'owner')~=owner or
 redis.call('HGET',KEYS[1],'closed')~='0' then return {'fenced'} end
local expiry=tonumber(redis.call('HGET',KEYS[1],'expiry'))
if not expiry or now>=expiry then return {'expired'} end
local prior=redis.call('HGET',KEYS[3],offset)
if prior then
 local decoded=cjson.decode(prior)
 if decoded[1]~=digest then return {'mismatch'} end
 return {'ok',decoded[2]}
end
if tonumber(offset)~=tonumber(redis.call('HGET',KEYS[1],'last'))+1 then
 return {'gap'}
end
if string.len(body)>16384 then return {'size'} end
local bytes=tonumber(redis.call('HGET',KEYS[1],'bytes'))+string.len(body)
local rows=tonumber(redis.call('HGET',KEYS[1],'rows'))+1
if bytes>tonumber(bytecap) or rows>tonumber(rowcap) then return {'capacity'} end
local cursor=redis.call('XADD',KEYS[2],'*','frame',body)
redis.call('HSET',KEYS[3],offset,cjson.encode({digest,cursor}))
redis.call('HSET',KEYS[1],'last',offset,'cursor',cursor,'bytes',bytes,'rows',rows)
local maximum=redis.call('HGET',KEYS[1],'maximum')
redis.call('PEXPIREAT',KEYS[2],maximum); redis.call('PEXPIREAT',KEYS[3],maximum)
return {'ok',cursor}
"""

INVALIDATE = """
if redis.call('HGET',KEYS[1],'generation')==ARGV[1] and
 redis.call('HGET',KEYS[1],'closed')~='1' then
 redis.call('HSET',KEYS[1],'closed','1','retired:'..ARGV[1],'1',
  'revision',redis.call('HGET',KEYS[1],'revision')..':closed')
 redis.call('XADD',KEYS[4],'MAXLEN','~',256,'*','generation',ARGV[1])
 redis.call('PEXPIREAT',KEYS[4],redis.call('HGET',KEYS[1],'laneend'))
end
return {'ok'}
"""

READ = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
if now>=tonumber(ARGV[2]) or
 redis.call('HGET',KEYS[1],'generation')~=ARGV[1] or
 redis.call('HGET',KEYS[1],'closed')~='0' or
 now>=tonumber(redis.call('HGET',KEYS[1],'expiry') or '0') then return {'resync'} end
local last=redis.call('HGET',KEYS[1],'last')
local head=redis.call('HGET',KEYS[1],'cursor')
if ARGV[3]=='barrier' then return {'ok',head,last} end
local offset=tonumber(ARGV[5])
if offset>tonumber(last) then return {'resync'} end
if offset>=0 then
 local prior=redis.call('HGET',KEYS[3],tostring(offset))
 if not prior or cjson.decode(prior)[2]~=ARGV[3] then return {'resync'} end
elseif ARGV[3]~='0-0' then return {'resync'} end
local entries=redis.call('XRANGE',KEYS[2],'('..ARGV[3],'+','COUNT',ARGV[4])
local result={'ok'}; local bytes=0
for _,entry in ipairs(entries) do
 local body=entry[2][2]
 bytes=bytes+string.len(body)
 if bytes>262144 then break end
 local frame=cjson.decode(body)
 if frame.offset~=offset+1 then return {'resync'} end
 offset=frame.offset
 table.insert(result,entry[1]); table.insert(result,body)
end
if #result==1 and offset<tonumber(last) then return {'resync'} end
return result
"""
