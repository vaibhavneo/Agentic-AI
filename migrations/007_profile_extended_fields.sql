-- P1 hardening pass: two informational-only profile fields surfaced in the
-- Health & Safety section. Neither drives any deterministic logic — they're
-- context for the user and for the AI Coach's get_user_profile tool call,
-- same as `notes` elsewhere in the schema.
ALTER TABLE profiles ADD COLUMN primary_health_goals TEXT;
ALTER TABLE profiles ADD COLUMN exercise_limitations TEXT;
