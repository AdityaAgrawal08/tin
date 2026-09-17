-- strategy.prescribe and strategy.wildcards are retired in favour of the growth onboarding
-- workflows. Their registry rows stay so past runs keep their pinned definitions, but archived
-- rows no longer list, resolve, or start.
UPDATE workflows
SET status = 'archived', updated_at = now()
WHERE project_id IS NULL
  AND id IN (
    '00000000-0000-4000-8000-000000000018',
    '00000000-0000-4000-8000-000000000019'
  )
  AND status <> 'archived';
