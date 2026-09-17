UPDATE outreach_deliveries AS delivery
SET scheduled_for = recipient.initial_sent_at
        + make_interval(days => campaign.follow_up_delay_days),
    updated_at = now()
FROM outreach_recipients AS recipient
JOIN outreach_campaigns AS campaign
  ON campaign.run_id = recipient.campaign_run_id
WHERE delivery.recipient_id = recipient.id
  AND delivery.campaign_run_id = campaign.run_id
  AND delivery.step_key = 'follow_up'
  AND delivery.status = 'pending'
  AND delivery.scheduled_for IS NULL
  AND recipient.initial_sent_at IS NOT NULL
  AND campaign.follow_up_delay_days IS NOT NULL;

WITH campaign_progress AS (
    SELECT campaign.run_id,
           campaign.status,
           campaign.send_timezone,
           count(delivery.execution_key) AS total,
           count(delivery.execution_key) FILTER (
               WHERE delivery.status IN ('sent', 'skipped')
           ) AS resolved,
           count(delivery.execution_key) FILTER (
               WHERE delivery.status = 'started'
                  OR (
                      delivery.status = 'pending'
                      AND (
                          delivery.scheduled_for IS NULL
                          OR delivery.scheduled_for <= now()
                      )
                  )
           ) AS ready,
           min(delivery.scheduled_for) FILTER (
               WHERE delivery.status = 'pending'
                 AND delivery.scheduled_for > now()
           ) AS next_delivery_at
    FROM outreach_campaigns AS campaign
    JOIN outreach_deliveries AS delivery
      ON delivery.campaign_run_id = campaign.run_id
    WHERE campaign.status IN ('draft', 'approved', 'running')
    GROUP BY campaign.run_id, campaign.status, campaign.send_timezone
), repaired AS (
    SELECT run_id,
           total,
           resolved,
           CASE
               WHEN status = 'draft' THEN 'review'
               WHEN resolved >= total THEN 'finishing'
               WHEN ready > 0 THEN 'sending'
               ELSE 'waiting'
           END AS step,
           CASE
               WHEN status = 'draft' THEN
                   'Preparing ' || total || ' '
                       || CASE WHEN total = 1 THEN 'email' ELSE 'emails' END
                       || ' for review'
               WHEN resolved >= total THEN 'Finishing the approved email campaign'
               WHEN ready > 0 THEN
                   'Sending ' || (total - resolved) || ' approved '
                       || CASE WHEN total - resolved = 1 THEN 'email' ELSE 'emails' END
               WHEN next_delivery_at IS NOT NULL THEN
                   'Waiting until '
                       || lower(to_char(next_delivery_at AT TIME ZONE send_timezone, 'Dy HH24:MI'))
                       || ' for the next approved email'
               ELSE 'Waiting for the next approved email'
           END AS summary
    FROM campaign_progress
    WHERE total > 0
)
UPDATE workflow_runs AS run
SET progress_mode = 'units',
    progress_step = repaired.step,
    progress_current = repaired.resolved,
    progress_total = repaired.total,
    progress_percent = (repaired.resolved * 100) / repaired.total,
    progress_summary = repaired.summary,
    progress_updated_at = now()
FROM repaired
WHERE run.id = repaired.run_id
  AND run.status IN ('pending', 'running', 'needs_input');
