-- Keep legacy integer projection while preserving exact typed values separately.
ALTER TABLE evidence_artifacts ADD COLUMN confirmed_prediction_json TEXT CHECK (confirmed_prediction_json IS NULL OR json_valid(confirmed_prediction_json));
UPDATE evidence_artifacts SET confirmed_prediction_json = CASE
    WHEN json_type(artifact_json, '$.confirmed_prediction') IS NULL OR json_type(artifact_json, '$.confirmed_prediction') = 'null' THEN NULL
    ELSE artifact_json -> '$.confirmed_prediction'
END;
