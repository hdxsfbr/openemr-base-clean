-- Data-quality audit queries (read-only). Run 2026-09-14 against the pristine
-- demo dataset in the local easy-development MariaDB 11.8.8 container.
-- Invocation: docker exec -i development-easy-mysql-1 mariadb -u<dev user> -p<dev password> openemr -t < queries.sql
-- (credentials: docker/development-easy/docker-compose.yml; intentionally not recorded here)
-- Every statement is SELECT / SHOW COLUMNS / information_schema only.

-- Q1 Volume inventory
SELECT 'patient_data',COUNT(*) FROM patient_data UNION ALL
SELECT 'form_encounter',COUNT(*) FROM form_encounter UNION ALL
SELECT 'forms',COUNT(*) FROM forms UNION ALL
SELECT 'pnotes',COUNT(*) FROM pnotes UNION ALL
SELECT 'lists',COUNT(*) FROM lists UNION ALL
SELECT 'prescriptions',COUNT(*) FROM prescriptions UNION ALL
SELECT 'immunizations',COUNT(*) FROM immunizations UNION ALL
SELECT 'procedure_order',COUNT(*) FROM procedure_order UNION ALL
SELECT 'procedure_report',COUNT(*) FROM procedure_report UNION ALL
SELECT 'procedure_result',COUNT(*) FROM procedure_result UNION ALL
SELECT 'history_data',COUNT(*) FROM history_data UNION ALL
SELECT 'form_clinical_notes',COUNT(*) FROM form_clinical_notes UNION ALL
SELECT 'form_soap',COUNT(*) FROM form_soap UNION ALL
SELECT 'form_vitals',COUNT(*) FROM form_vitals UNION ALL
SELECT 'lists_medication',COUNT(*) FROM lists_medication UNION ALL
SELECT 'issue_encounter',COUNT(*) FROM issue_encounter UNION ALL
SELECT 'documents',COUNT(*) FROM documents UNION ALL
SELECT 'drugs',COUNT(*) FROM drugs UNION ALL
SELECT 'form_observation',COUNT(*) FROM form_observation UNION ALL
SELECT 'form_care_plan',COUNT(*) FROM form_care_plan UNION ALL
SELECT 'external_encounters',COUNT(*) FROM external_encounters UNION ALL
SELECT 'openemr_postcalendar_events',COUNT(*) FROM openemr_postcalendar_events;
SELECT formdir, deleted, COUNT(*) FROM forms GROUP BY formdir, deleted;
SELECT type, activity, COUNT(*) FROM lists GROUP BY type, activity;
SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES
 WHERE TABLE_SCHEMA='openemr' AND TABLE_NAME LIKE 'form\_%' AND TABLE_ROWS>0;
SELECT VERSION(), @@time_zone, @@system_time_zone, @@sql_mode;

-- Q2 lists profile (title length only, never title text)
SELECT id,pid,type,CHAR_LENGTH(title) tlen,begdate,enddate,activity,diagnosis,verification,
       reaction,severity_al,outcome,date,modifydate,list_option_id,subtype,CHAR_LENGTH(comments) clen,
       occurrence,user,uuid IS NULL nouuid,external_id,erx_source,erx_uploaded
  FROM lists ORDER BY pid,type;
SELECT (SELECT COUNT(*) FROM lists WHERE type='allergy' AND (reaction='' OR reaction IS NULL)) allergy_no_reaction,
       (SELECT COUNT(*) FROM lists WHERE type='allergy' AND severity_al IS NULL) allergy_no_sev,
       (SELECT COUNT(*) FROM lists WHERE diagnosis='' OR diagnosis IS NULL) lists_uncoded,
       (SELECT COUNT(*) FROM lists WHERE verification='') no_verif,
       (SELECT COUNT(*) FROM lists WHERE begdate IS NULL) no_begdate;
SELECT (SELECT COUNT(*) FROM lists WHERE date<'2015-01-01') created_2014,
       (SELECT COUNT(*) FROM lists WHERE modifydate>'2026-01-01') modified_2026,
       (SELECT COUNT(DISTINCT DATE(date)) FROM form_encounter) enc_distinct_days;

-- Q3 Duplicate problems/meds/allergies within patient+type (normalized title equality)
SELECT a.id,b.id,a.pid,a.type,LOWER(TRIM(a.title))=LOWER(TRIM(b.title)) same_title
  FROM lists a JOIN lists b ON a.pid=b.pid AND a.type=b.type AND a.id<b.id;

-- Q4 prescriptions profile and lists(type=medication) overlap
SELECT id,patient_id,encounter,date_added,date_modified,start_date,end_date,active,rxnorm_drugcode,
       CHAR_LENGTH(drug) dlen,drug_id,dosage,quantity,size,unit,route,form,`interval`,refills,provider_id,
       usage_category,request_intent,indication,txDate,diagnosis,uuid IS NULL nouuid
  FROM prescriptions;
SELECT p.id, l.id lid, LOWER(TRIM(p.drug))=LOWER(TRIM(l.title)) exact,
       INSTR(LOWER(l.title),LOWER(SUBSTRING_INDEX(TRIM(p.drug),' ',1)))>0 firstword,
       l.activity, l.begdate, p.start_date
  FROM prescriptions p JOIN lists l ON l.pid=p.patient_id AND l.type='medication';
SELECT list_id, option_id, title FROM list_options
 WHERE (list_id='drug_units' AND option_id='1') OR (list_id='drug_route' AND option_id='1')
    OR (list_id='drug_form' AND option_id='2') OR (list_id='drug_interval' AND option_id='9');

-- Q5 Encounters, forms, notes, vitals
SELECT id,pid,encounter,date,onset_date,date_end,provider_id,supervisor_id,facility_id,pos_code,class_code,
       CHAR_LENGTH(reason) rlen,pc_catid,encounter_type_code,uuid IS NULL nouuid FROM form_encounter;
SELECT id,date,encounter,form_id,pid,user,authorized,deleted,formdir,provider_id,issue_id FROM forms ORDER BY encounter;
SELECT id,date,pid,user,authorized,activity,CHAR_LENGTH(subjective) s,CHAR_LENGTH(objective) o,
       CHAR_LENGTH(assessment) a,CHAR_LENGTH(plan) p FROM form_soap;
SELECT id,date,pid,user,authorized,bps,bpd,height,weight,temperature,temp_method,pulse,respiration,BMI,
       BMI_status,waist_circ,head_circ,oxygen_saturation,oxygen_flow_rate,last_updated FROM form_vitals;
SELECT (SELECT COUNT(*) FROM form_vitals WHERE waist_circ=0) waist_zero,
       (SELECT COUNT(*) FROM form_vitals WHERE oxygen_flow_rate=0) o2flow_zero;
SELECT (SELECT COUNT(*) FROM prescriptions WHERE txDate='0000-00-00') rx_zero_tx,
       (SELECT COUNT(*) FROM form_encounter WHERE onset_date='0000-00-00 00:00:00') enc_zero_onset;
SELECT pc_pid, pc_eventDate, pc_catid FROM openemr_postcalendar_events WHERE pc_pid<>'' AND pc_pid<>'0';
SELECT id, authorized, active, facility_id, npi IS NOT NULL AND npi<>'' has_npi FROM users WHERE id=1;

-- Q6 Patients / history (flags only)
SELECT pid, sex<>'' has_sex, DOB IS NULL OR DOB='0000-00-00' no_dob, uuid IS NULL nouuid, providerID,
       regdate, language<>'' lang, race<>'' race, ethnicity<>'' eth FROM patient_data;
SELECT id,pid,CHAR_LENGTH(tobacco) tob,CHAR_LENGTH(alcohol) alc, uuid IS NULL nouuid FROM history_data;

-- Q7 Orphans / consistency
SELECT 'forms_no_encounter',COUNT(*) FROM forms f LEFT JOIN form_encounter e ON e.encounter=f.encounter AND e.pid=f.pid WHERE e.id IS NULL UNION ALL
SELECT 'soap_no_forms',COUNT(*) FROM form_soap s LEFT JOIN forms f ON f.form_id=s.id AND f.formdir='soap' WHERE f.id IS NULL UNION ALL
SELECT 'vitals_no_forms',COUNT(*) FROM form_vitals s LEFT JOIN forms f ON f.form_id=s.id AND f.formdir='vitals' WHERE f.id IS NULL UNION ALL
SELECT 'soap_pid_mismatch',COUNT(*) FROM form_soap s JOIN forms f ON f.form_id=s.id AND f.formdir='soap' WHERE f.pid<>s.pid UNION ALL
SELECT 'lists_no_patient',COUNT(*) FROM lists l LEFT JOIN patient_data p ON p.pid=l.pid WHERE p.id IS NULL UNION ALL
SELECT 'rx_no_patient',COUNT(*) FROM prescriptions r LEFT JOIN patient_data p ON p.pid=r.patient_id WHERE p.id IS NULL UNION ALL
SELECT 'rx_no_encounter',COUNT(*) FROM prescriptions r LEFT JOIN form_encounter e ON e.encounter=r.encounter AND e.pid=r.patient_id WHERE e.id IS NULL UNION ALL
SELECT 'enc_no_patient',COUNT(*) FROM form_encounter e LEFT JOIN patient_data p ON p.pid=e.pid WHERE p.id IS NULL UNION ALL
SELECT 'enc_provider_missing',COUNT(*) FROM form_encounter e LEFT JOIN users u ON u.id=e.provider_id WHERE u.id IS NULL UNION ALL
SELECT 'enc_newpatient_form_missing',COUNT(*) FROM form_encounter e LEFT JOIN forms f ON f.encounter=e.encounter AND f.formdir='newpatient' WHERE f.id IS NULL UNION ALL
SELECT 'lists_enddate_past_active',COUNT(*) FROM lists WHERE activity=1 AND enddate IS NOT NULL AND enddate<NOW() UNION ALL
SELECT 'lists_inactive_no_enddate',COUNT(*) FROM lists WHERE activity=0 AND enddate IS NULL UNION ALL
SELECT 'issue_encounter_rows',COUNT(*) FROM issue_encounter UNION ALL
SELECT 'patients_with_gt1_encounter',COUNT(*) FROM (SELECT pid FROM form_encounter GROUP BY pid HAVING COUNT(*)>1) x UNION ALL
SELECT 'patients_with_0_encounter',COUNT(*) FROM patient_data p LEFT JOIN form_encounter e ON e.pid=p.pid WHERE e.id IS NULL UNION ALL
SELECT 'patients_with_0_lists',COUNT(*) FROM patient_data p LEFT JOIN lists l ON l.pid=p.pid WHERE l.id IS NULL;

-- Q8 "None recorded" attestation (lists_touch)
SELECT pid, type, date IS NULL nodate FROM lists_touch ORDER BY pid, type;
SELECT COUNT(*) pts_allergy_unknown FROM patient_data p
  LEFT JOIN lists_touch t ON t.pid=p.pid AND t.type='allergy'
  LEFT JOIN lists l ON l.pid=p.pid AND l.type='allergy'
 WHERE t.pid IS NULL AND l.id IS NULL;

-- Q9 Schema types for date / result / coded columns (empty tables profiled at schema level)
SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,IS_NULLABLE,COLUMN_DEFAULT FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA='openemr'
   AND TABLE_NAME IN ('lists','prescriptions','form_encounter','pnotes','form_clinical_notes','procedure_order',
                      'procedure_report','procedure_result','immunizations','form_vitals','lists_medication')
   AND (DATA_TYPE IN ('date','datetime','timestamp')
        OR COLUMN_NAME IN ('result','units','range','abnormal','result_code','result_data_type','diagnosis',
                           'rxnorm_drugcode','activity','active','unit','route','form','interval','dosage','code',
                           'codetext','clinical_notes_type','result_status','report_status','order_status',
                           'verification','severity_al','reaction','cvx_code'))
 ORDER BY TABLE_NAME, ORDINAL_POSITION;
SELECT COUNT(*) tz_aware_cols FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA='openemr' AND DATA_TYPE='timestamp'
   AND TABLE_NAME IN ('lists','prescriptions','form_encounter','pnotes','form_clinical_notes','procedure_result',
                      'procedure_report','procedure_order','form_soap','form_vitals','immunizations');

-- Q10 Terminology availability and relevant globals
SELECT code_type, COUNT(*) FROM codes GROUP BY code_type;
SELECT ct_key FROM code_types WHERE ct_active=1;
SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='openemr'
   AND (TABLE_NAME LIKE 'rxn%' OR TABLE_NAME LIKE 'sct%' OR TABLE_NAME LIKE 'valueset%');
SELECT (SELECT COUNT(*) FROM icd10_dx_order_code WHERE active=1) icd10_active,
       (SELECT COUNT(*) FROM icd9_dx_code WHERE active=1) icd9_active;
SELECT gl_name, gl_value FROM globals
 WHERE gl_name IN ('allow_issue_duplicates','erx_enable','units_of_measurement','gbl_time_zone',
                   'date_display_format','ccda_alt_service_enable','weno_rx_enable');
