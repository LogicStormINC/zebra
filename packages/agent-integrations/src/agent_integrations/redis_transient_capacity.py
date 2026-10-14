"""Specific transient accounting scripts; standalone Redis, never Cluster slots.

ponytail: one deployment hash holds atomic counters and operation seals. Its
cardinality is bounded by retained slots; simultaneous policy epochs need a
separate aggregate rule. Logical deletion is not a physical Redis RSS guarantee.
"""

# Keys: authority, frames, offsets, control, deployment ledger, due index, record.
# ARGV capacity tail: policy JSON, digest, tenant, Run, verified generation.
CAPACITY = """
local function kind(key, expected)
 local t=redis.call('TYPE',key).ok
 return t=='none' or t==expected
end
if not kind(KEYS[1],'hash') or not kind(KEYS[2],'stream') or
 not kind(KEYS[3],'hash') or not kind(KEYS[4],'stream') or
 not kind(KEYS[5],'hash') or not kind(KEYS[6],'zset') or
 not kind(KEYS[7],'hash') then return {'key_type'} end
local policy=cjson.decode(ARGV[#ARGV-4])
local pdigest,tenant,run=ARGV[#ARGV-3],ARGV[#ARGV-2],ARGV[#ARGV-1]
local immutable=cjson.encode({KEYS,ARGV[#ARGV],tenant,run,pdigest})
if redis.call('HGET',KEYS[5],'epoch')~=policy.epoch or
 redis.call('HGET',KEYS[5],'digest')~=pdigest then return {'unsealed'} end
local record=KEYS[7]
local groups={'deployment','tenant:'..tenant,'run:'..run}
local function counters(group)
 local value=redis.call('HGET',KEYS[5],group)
 if not value then
  if group=='deployment' or redis.call('HEXISTS',KEYS[5],'seen:'..group)==1 then return nil end
  return {0,0,0}
 end
 local ok,decoded=pcall(cjson.decode,value)
 if not ok or #decoded~=3 then return nil end
 for _,n in ipairs(decoded) do
  if type(n)~='number' or n<0 or n>9007199254740991 or n%1~=0 then return nil end
 end
 return decoded
end
local function charge(bytes,rows,slots,checkonly)
 local edits={}
 for i,group in ipairs(groups) do
  local prior=counters(group)
  if not prior then return 'corrupt' end
  local label=({'deployment','tenant','run'})[i]
  if prior[1]+bytes>policy[label..'_bytes'] or
   prior[2]+rows>policy[label..'_rows'] or
   prior[3]+slots>policy[label..'_slots'] then return 'capacity' end
  table.insert(edits,'seen:'..group); table.insert(edits,'1')
  table.insert(edits,group)
  table.insert(edits,cjson.encode({prior[1]+bytes,prior[2]+rows,prior[3]+slots}))
 end
 local old=redis.call('HGET',KEYS[5],'charge:'..record)
 local bound=redis.call('HGET',KEYS[5],'binding:'..record)
 if (old and not bound) or (bound and bound~=immutable) then return 'corrupt' end
 local totals=old and cjson.decode(old) or {0,0,0}
 table.insert(edits,'seencharge:'..record); table.insert(edits,'1')
 table.insert(edits,'binding:'..record); table.insert(edits,immutable)
 table.insert(edits,'charge:'..record)
 table.insert(edits,cjson.encode({totals[1]+bytes,totals[2]+rows,totals[3]+slots}))
 if checkonly then return nil end
 -- Counter updates and their recovery seal are ONE atomic hash command.
 redis.call('HSET',KEYS[5],unpack(edits))
 return nil
end
local function clean()
 if redis.call('HGET',KEYS[5],'binding:'..record)~=immutable then return false end
 if redis.call('HGET',record,'dirty')~='0' or
  redis.call('HGET',record,'digest')~=pdigest or
  redis.call('HGET',record,'tenant')~=tenant or redis.call('HGET',record,'run')~=run or
  redis.call('ZSCORE',KEYS[6],record)==false then return false end
 local raw=redis.call('HGET',KEYS[5],'charge:'..record)
 if not raw then return false end
 local valid,amounts=pcall(cjson.decode,raw)
 if not valid or #amounts~=3 then return false end
 for _,group in ipairs(groups) do
  local value=counters(group)
  if not value then return false end
  for i=1,3 do
   if type(amounts[i])~='number' or amounts[i]<0 or amounts[i]%1~=0 or
    amounts[i]>9007199254740991 or value[i]<amounts[i] then return false end
  end
 end
 return true
end
local function dirty(operation)
 local t=redis.call('TIME')
 redis.call('ZADD',KEYS[6],t[1]*1000+math.floor(t[2]/1000),record)
 redis.call('HSET',record,'dirty',operation)
 redis.call('HSET',KEYS[1],'dirty','1')
end
local function finish()
 -- All authority/body/accounting writes are complete before clearing the intent.
 redis.call('HSET',KEYS[1],'dirty','0')
 redis.call('HSET',record,'dirty','0')
 -- A failed final reschedule leaves a clean, fully charged record due now. GC
 -- requeues its actual deadline rather than deleting or refunding it early.
 redis.call('ZADD',KEYS[6],redis.call('HGET',record,'deadline'),record)
end
"""

READ_BOUND = """
local digest=redis.call('HGET',KEYS[5],'digest')
local binding=redis.call('HGET',KEYS[5],'binding:'..KEYS[7])
if not digest or not binding or binding~=cjson.encode({KEYS,ARGV[1],
 ARGV[#ARGV-1],ARGV[#ARGV],digest}) then return {'resync'} end
"""

SNAPSHOT = CAPACITY + """
if redis.call('HGET',KEYS[1],'dirty')=='1' then return {'dirty'} end
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local expiry=math.min(tonumber(ARGV[2]),now+30000)
local created=false
if expiry<=now then return {'expired'} end
if redis.call('EXISTS',record)==1 then
 if not clean() then return {'dirty'} end
 if tonumber(redis.call('HGET',record,'deadline'))<=now then return {'expired'} end
else
 if redis.call('EXISTS',KEYS[2])==1 or redis.call('EXISTS',KEYS[3])==1 or
  redis.call('HEXISTS',KEYS[5],'charge:'..record)==1 then return {'lost'} end
 if redis.call('ZCARD',KEYS[6])>=policy.deployment_slots then return {'capacity'} end
 local problem=charge(policy.metadata_bytes,0,1,true)
 if problem then return {problem} end
 -- Index first: a partial reservation stays discoverable, never grants authority.
 redis.call('ZADD',KEYS[6],now,record)
 redis.call('HSET',record,'dirty','snapshot','digest',pdigest,'tenant',tenant,'run',run,
  'deadline',expiry,'keys',cjson.encode(KEYS),'generation',ARGV[3],'rows','0','bytes','0')
 problem=charge(policy.metadata_bytes,0,1)
 if problem then return {problem} end
 redis.call('HSET',record,'dirty','0')
 redis.call('ZADD',KEYS[6],expiry,record)
 created=true
end
local revision=redis.call('HGET',KEYS[1],'revision')
if created or not revision then
 revision=ARGV[1]
 redis.call('HSET',KEYS[1],'revision',revision,'reservation_record',record)
 local laneend=math.max(tonumber(redis.call('HGET',KEYS[1],'laneend') or '0'),expiry)
 redis.call('HSET',KEYS[1],'laneend',laneend)
 redis.call('PEXPIREAT',KEYS[1],laneend)
end
return {'ok',revision}
"""

BEFORE_ACTIVATE = CAPACITY + """
if not clean() or redis.call('HGET',KEYS[1],'dirty')=='1' then return {'dirty'} end
"""

ACTIVATION_RETENTION = """
if redis.call('HGET',record,'active')=='1' then
 maximum=tonumber(redis.call('HGET',record,'deadline'))
end
maximum=math.min(maximum,now+policy.active_seconds*1000)
if maximum<=now then return {'expired'} end
local descriptor=ARGV[10] or ''
if string.len(descriptor)+2*(string.len(KEYS[1])+string.len(KEYS[2])+string.len(KEYS[3])+
 string.len(KEYS[4])+string.len(KEYS[5])+string.len(KEYS[6])+string.len(KEYS[7]))+4096>
 policy.metadata_bytes then return {'descriptor_size'} end
-- Index remains the original reservation deadline until activation finishes.
dirty('activate')
"""

AFTER_ACTIVATE = """
redis.call('HSET',record,'active','1','deadline',maximum,'ended_seconds',policy.ended_seconds)
redis.call('HSET',KEYS[1],'activation_record',record)
if redis.call('HGET',KEYS[1],'reservation_record')==record then
 redis.call('HDEL',KEYS[1],'reservation_record')
end
-- Shared lane metadata survives every retained generation, never the first lane end.
local laneend=math.max(tonumber(redis.call('HGET',KEYS[1],'laneend') or '0'),maximum)
redis.call('HSET',KEYS[1],'laneend',laneend)
redis.call('PEXPIREAT',KEYS[1],laneend); redis.call('PEXPIREAT',KEYS[4],laneend)
finish()
return {'ok'}
"""

BEFORE_PUBLISH = CAPACITY + """
if not clean() or redis.call('HGET',KEYS[1],'dirty')=='1' then return {'dirty'} end
"""

PUBLISH_CHARGE = """
local offsetbody=cjson.encode({digest,'9999999999999999-9999999999999999'})
if string.len(offsetbody)+string.len(offset)>policy.offset_bytes then return {'size'} end
if bytes>policy.generation_bytes or rows>policy.generation_rows then return {'capacity'} end
dirty('publish:'..offset)
local problem=charge(string.len(body)+policy.offset_bytes,1,0)
if problem then return {problem} end
"""

AFTER_PUBLISH = """
redis.call('HSET',record,'bytes',bytes,'rows',rows)
finish()
return {'ok',cursor}
"""

INVALIDATE = CAPACITY + """
if not clean() then return {'dirty'} end
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local deadline=math.min(tonumber(redis.call('HGET',record,'deadline')),
 now+policy.ended_seconds*1000)
dirty('invalidate')
if redis.call('HGET',KEYS[1],'generation')==ARGV[1] and
 redis.call('HGET',KEYS[1],'closed')~='1' then
 redis.call('HSET',KEYS[1],'closed','1','retired:'..ARGV[1],'1',
  'revision',redis.call('HGET',KEYS[1],'revision')..':closed')
 redis.call('XADD',KEYS[4],'MAXLEN','~',256,'*','generation',ARGV[1])
end
redis.call('PEXPIREAT',KEYS[2],deadline); redis.call('PEXPIREAT',KEYS[3],deadline)
redis.call('HSET',record,'deadline',deadline)
finish()
return {'ok'}
"""

# Only explicit cutover may initialize. Lost ledgers are never reconstructed by writers.
SEAL = """
if redis.call('TYPE',KEYS[1]).ok~='none' then
 if redis.call('TYPE',KEYS[1]).ok~='hash' then return {'key_type'} end
 if redis.call('HGET',KEYS[1],'epoch')==ARGV[1] and
  redis.call('HGET',KEYS[1],'digest')==ARGV[2] then return {'ok'} end
 if redis.call('ZCARD',KEYS[2])~=0 or
  redis.call('HGET',KEYS[1],'deployment')~='[0,0,0]' or
  redis.call('HLEN',KEYS[1])>4 then return {'epoch'} end
end
if redis.call('ZCARD',KEYS[2])~=0 then return {'lost'} end
for i=3,#KEYS do if redis.call('EXISTS',KEYS[i])~=0 then return {'old_keys'} end end
redis.call('HSET',KEYS[1],'epoch',ARGV[1],'digest',ARGV[2],'deployment','[0,0,0]')
return {'ok'}
"""

GC = """
local function kind(key,expected)
 local value=redis.call('TYPE',key).ok; return value=='none' or value==expected
end
if not kind(KEYS[1],'hash') or not kind(KEYS[2],'zset') then return {'key_type'} end
local lost=redis.call('TYPE',KEYS[1]).ok=='none'
if lost then return {'unsealed'} end
local digest=redis.call('HGET',KEYS[1],'digest')
if not digest or not redis.call('HGET',KEYS[1],'epoch') then
 return {'unsealed'} end
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
local due=redis.call('ZRANGEBYSCORE',KEYS[2],'-inf',now,'LIMIT',0,ARGV[3])
local completed=0
for _,record in ipairs(due) do
 local clock=redis.call('TIME')
 if clock[1]*1000+math.floor(clock[2]/1000)-now>=tonumber(ARGV[4]) then break end
 if not kind(record,'hash') then return {'key_type'} end
 local rawkeys=redis.call('HGET',record,'keys')
 local charge=redis.call('HGET',KEYS[1],'charge:'..record)
 if not charge and redis.call('HEXISTS',KEYS[1],'seencharge:'..record)==1 then
  return {'corrupt'} end
 if rawkeys and redis.call('HGET',record,'dirty')=='0' and
  tonumber(redis.call('HGET',record,'deadline') or '0')>now then
  redis.call('ZADD',KEYS[2],redis.call('HGET',record,'deadline'),record)
 else
 if not rawkeys then
  if charge then return {'corrupt'} end
  redis.call('ZREM',KEYS[2],record)
 else
  if redis.call('HGET',record,'digest')~=digest then return {'corrupt'} end
  local keys=cjson.decode(rawkeys)
  local binding=redis.call('HGET',KEYS[1],'binding:'..record)
  local expected=cjson.encode({keys,redis.call('HGET',record,'generation'),
   redis.call('HGET',record,'tenant'),redis.call('HGET',record,'run'),digest})
  if not binding or binding~=expected then return {'corrupt'} end
  local prefix=string.match(KEYS[1],'^(.*):capacity:[^:]+$')
  local gen=redis.call('HGET',record,'generation')
  local lane=keys[1] and string.match(keys[1],'^(.*):authority$')
  if #keys~=7 or not lane or string.sub(lane,1,string.len(prefix)+1)~=prefix..':' or
   keys[2]~=lane..':'..gen..':frames' or keys[3]~=lane..':'..gen..':offsets' or
   keys[4]~=keys[1]..':control' or
   keys[5]~=KEYS[1] or keys[6]~=KEYS[2] or keys[7]~=record then
   return {'corrupt'} end
  if not kind(keys[1],'hash') or not kind(keys[2],'stream') or
   not kind(keys[3],'hash') or not kind(keys[4],'stream') then return {'key_type'} end
  local generation=redis.call('HGET',record,'generation')
  local groups={'deployment','tenant:'..redis.call('HGET',record,'tenant'),
   'run:'..redis.call('HGET',record,'run')}
  local edits={}
  if charge and charge~='[0,0,0]' then
   local valid,amounts=pcall(cjson.decode,charge)
   if not valid or #amounts~=3 then return {'corrupt'} end
   for _,n in ipairs(amounts) do
    if type(n)~='number' or n<0 or n%1~=0 or n>9007199254740991 then
     return {'corrupt'} end
   end
   for _,group in ipairs(groups) do
    local raw=redis.call('HGET',KEYS[1],group)
    if not raw then return {'corrupt'} end
    local valid,values=pcall(cjson.decode,raw)
    if not valid or #values~=3 then return {'corrupt'} end
    for i=1,3 do
     if type(values[i])~='number' or values[i]%1~=0 or
      values[i]>9007199254740991 then return {'corrupt'} end
     values[i]=values[i]-amounts[i]
     if values[i]<0 then return {'corrupt'} end
    end
    table.insert(edits,group); table.insert(edits,cjson.encode(values))
   end
  end
  redis.call('HSET',record,'dirty','gc')
  -- Exact body deletion PRECEDES accounting release; repeat delete is harmless.
  redis.call('UNLINK',keys[2],keys[3])
  local current=redis.call('HGET',keys[1],'generation')
  local reserved=redis.call('HGET',keys[1],'reservation_record')
  local active=redis.call('HGET',keys[1],'activation_record')
  if reserved==record then
   redis.call('HDEL',keys[1],'reservation_record'); reserved=false
  end
  if (not current and not reserved) or
   (current==generation and active==record and not reserved) then
   redis.call('DEL',keys[1],keys[4])
  elseif current==generation and active==record then
   -- A newer reservation owns the revision: preserve its absent-state CAS.
   redis.call('HDEL',keys[1],'generation','activation_record','descriptor','expiry',
    'maximum','closed','owner','epoch','token','rows','bytes','last','cursor')
  else redis.call('HDEL',keys[1],'retired:'..generation) end
  if charge then
   -- Counter+release-once seal in the SAME hash mutation, even on a lost reply.
   table.insert(edits,'charge:'..record); table.insert(edits,'[0,0,0]')
   redis.call('HSET',KEYS[1],unpack(edits))
  end
  -- Empty Run/tenant ledgers are bounded by retained slots, not historical Runs.
  for i=2,3 do
   if redis.call('HGET',KEYS[1],groups[i])=='[0,0,0]' then
    redis.call('HDEL',KEYS[1],groups[i],'seen:'..groups[i])
   end
  end
  redis.call('HDEL',KEYS[1],'charge:'..record,'seencharge:'..record,'binding:'..record)
  redis.call('DEL',record); redis.call('ZREM',KEYS[2],record)
 end
 completed=completed+1
 end
end
return {'ok',tostring(completed)}
"""
