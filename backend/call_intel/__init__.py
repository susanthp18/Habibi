"""Call intelligence: the batch pass over every finished call.

A finished call (Voice Studio today) gets one ``call_intelligence_jobs`` row.
The ``ml_worker`` process (``python -m call_intel.worker``) claims it and runs
the stages in order, each idempotent and recorded on the job:

* ``pii``     -- find PII in the unmasked words (``pii.py``), file the
                 redaction record and its findings, re-mask the stored transcript.
* ``audio``   -- time each finding on the speaker's track and beep it
                 (``audio.py``): the redacted recording and its segments.
* ``signals`` -- per-turn sentiment, intents, agent behaviour, disclosures.
* ``qa``      -- the QA cascade: evidence, small models, then the LLM judge
                 only where they are unsure.

Models are small, pinned, baked into the image and run on CPU (``models.py``).
"""
