-- Use the firmware model code for WS-50 records created by early bridges.
-- IDs and relationships stay intact, including readings and sync receipts.
UPDATE scales SET model='WBS02' WHERE model='WS50';

-- A restore preview may already be staged when the server is upgraded.
UPDATE backup_staging_rows
SET row_json=json_set(row_json,'$.model','WBS02')
WHERE section='scales' AND json_extract(row_json,'$.model')='WS50';
