CREATE TABLE workflow_systems (
    id text PRIMARY KEY
        CHECK (id ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$' AND length(id) <= 80),
    name text NOT NULL
        CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    display_order integer NOT NULL
        CHECK (display_order >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX workflow_systems_display_order_idx
ON workflow_systems (display_order, name);
