-- Wave 6 counts only. Do not SELECT text.
-- Usage: docker exec collections_db psql -U collections -d collections -f - < this file
-- (pipe via stdin; do not docker compose exec)

SELECT to_regclass('perception_facts') AS perception_facts,
       to_regclass('perception_runs') AS perception_runs,
       to_regclass('understanding_decisions') AS understanding_decisions;

SELECT count(*) AS transcript_rows FROM interaction_transcript;
SELECT speaker, count(*) FROM interaction_transcript GROUP BY 1 ORDER BY 2 DESC;
SELECT coalesce(intent,'(null)') AS intent, count(*) FROM interaction_transcript GROUP BY 1 ORDER BY 2 DESC;
SELECT count(*) FILTER (WHERE intent_score IS NOT NULL) AS scored,
       count(*) FILTER (WHERE sentiment_delta IS NOT NULL) AS with_sentiment
FROM interaction_transcript;

SELECT count(*) AS customer_rows FROM customers_pii;
SELECT coalesce(language,'(null)') AS language, count(*) FROM customers_pii GROUP BY 1 ORDER BY 2 DESC;

SELECT count(*) FILTER (WHERE text ~ '[\u0900-\u097F]') AS devanagari,
       count(*) FILTER (WHERE text ~ '[\u0B80-\u0BFF]') AS tamil,
       count(*) FILTER (WHERE text ~ '[\u0C00-\u0C7F]') AS telugu,
       count(*) FILTER (WHERE text ~ '[\u0A80-\u0AFF]') AS gujarati,
       count(*) FILTER (WHERE text ~ '[\u0980-\u09FF]') AS bengali,
       count(*) FILTER (WHERE text ~ '[\u0C80-\u0CFF]') AS kannada,
       count(*) FILTER (WHERE text ~ '[\u0900-\u097F]|[\u0B80-\u0BFF]') AS any_indic_script
FROM interaction_transcript WHERE speaker='customer';

SELECT count(*) FILTER (
  WHERE text ~* '\y(namaste|haan|nahi|nahin|kya|aap|mujhe|mera|bahut|theek|accha|samajh|paisa|kitna)\y'
) AS hindi_latin_marker_rows
FROM interaction_transcript WHERE speaker='customer';

SELECT count(*) AS perception_facts FROM perception_facts;
SELECT count(*) AS perception_runs FROM perception_runs;
SELECT outcome, count(*) FROM perception_runs GROUP BY 1 ORDER BY 2 DESC;
SELECT source_model, count(*) FROM perception_facts GROUP BY 1 ORDER BY 2 DESC;

SELECT count(*) AS media_rows FROM interaction_media;
SELECT kind, count(*) FROM interaction_media GROUP BY 1 ORDER BY 2 DESC;
