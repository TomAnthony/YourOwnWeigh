-- Dummy device for local Worker integration tests only. Never apply remotely.
INSERT INTO scales(id,label,model,mac,secret,goff,dst,ngoff,time_zone,feature_mask,beta_ws,temp_code,
                   weight_code,settings_ready,roster_enabled,roster_snapshot,screen_response,summary_response)
VALUES(1,'Test scale','WBS06','24E42F123456','private-device-secret',3600,0,3600,'Europe/Berlin',7,0,13,
       14,1,1,'[{"id":17,"sn":"OLD","ht":1.8,"agt":40,"sx":1,"wt":73,"cr":123,"fm":0,"att":0,"cs":"","ptf":0,"bd":0}]',
       '{"status":0,"body":{"device":[],"user":[]}}','{"status":0,"body":[]}')
ON CONFLICT(id) DO UPDATE SET secret=excluded.secret,settings_ready=excluded.settings_ready,
  roster_enabled=excluded.roster_enabled,roster_snapshot=excluded.roster_snapshot,
  time_zone=excluded.time_zone,screen_response=excluded.screen_response,
  summary_response=excluded.summary_response;
INSERT INTO users(id,name,short_name,height_cm,age_years,sex,reference_weight_kg,created_at)
VALUES(17,'Test user','TST',181,40,0,73,1)
ON CONFLICT(id) DO UPDATE SET short_name=excluded.short_name,height_cm=excluded.height_cm,
  age_years=excluded.age_years,sex=excluded.sex,reference_weight_kg=excluded.reference_weight_kg;
INSERT INTO scale_users(scale_id,user_id,rank) VALUES(1,17,1)
ON CONFLICT(scale_id,user_id) DO UPDATE SET rank=excluded.rank;

-- WS-30 has no WBS06 fixtures or settings prerequisite.
INSERT INTO scales(id,label,model,mac,secret,time_zone)
VALUES(2,'Test WS-30','WBS03','001122334466','0123456789abcdef','Europe/Berlin')
ON CONFLICT(id) DO UPDATE SET model=excluded.model,secret=excluded.secret,time_zone=excluded.time_zone;
