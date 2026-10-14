"""Atomic temporary text transport. Redis time owns expiry checks."""

from agent_integrations import redis_transient_capacity as capacity

SNAPSHOT = capacity.SNAPSHOT
INVALIDATE = capacity.INVALIDATE

ACTIVATE = capacity.BEFORE_ACTIVATE + """
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

 end
end
""" + capacity.ACTIVATION_RETENTION + """
if old and old~=gen then redis.call('HSET',KEYS[1],'retired:'..old,'1') end
if not old then redis.call('HSET',KEYS[1],'generations','1')
elseif old~=gen then redis.call('HINCRBY',KEYS[1],'generations',1) end
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
""" + capacity.AFTER_ACTIVATE

PUBLISH = capacity.BEFORE_PUBLISH + """
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
""" + capacity.PUBLISH_CHARGE + """
local cursor=redis.call('XADD',KEYS[2],'*','frame',body)
redis.call('HSET',KEYS[3],offset,cjson.encode({digest,cursor}))
redis.call('HSET',KEYS[1],'last',offset,'cursor',cursor,'bytes',bytes,'rows',rows)
local maximum=redis.call('HGET',KEYS[1],'maximum')
redis.call('PEXPIREAT',KEYS[2],maximum); redis.call('PEXPIREAT',KEYS[3],maximum)
""" + capacity.AFTER_PUBLISH

READ = """
local record=KEYS[7]
local tenant=redis.call('HGET',record,'tenant')
local run=redis.call('HGET',record,'run')
local raw=redis.call('HGET',KEYS[5],'charge:'..record)
if not tenant or not run or not raw then return {'resync'} end
local ok,amounts=pcall(cjson.decode,raw)
if not ok then return {'resync'} end
for _,group in ipairs({'deployment','tenant:'..tenant,'run:'..run}) do
 local value=redis.call('HGET',KEYS[5],group)
 if not value then return {'resync'} end
 local valid,totals=pcall(cjson.decode,value)
 if not valid or #totals~=3 then return {'resync'} end
 for i=1,3 do
  if type(totals[i])~='number' or totals[i]<amounts[i] then return {'resync'} end
 end
end
if redis.call('HGET',KEYS[7],'dirty')~='0' or
 redis.call('HGET',KEYS[1],'dirty')=='1' or
 redis.call('HEXISTS',KEYS[5],'charge:'..KEYS[7])~=1 then return {'resync'} end

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
