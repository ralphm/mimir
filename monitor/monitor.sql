CREATE TABLE presences (
    presence_id serial PRIMARY KEY,
    jid text NOT NULL,
    resource text NOT NULL,
    type text DEFAULT 'unavailable' NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    status text,
    show text,
    last_updated timestamp with time zone DEFAULT now()
);

CREATE TABLE roster (
    jid text NOT NULL PRIMARY KEY,
    presence_id integer NOT NULL
        REFERENCES presences (presence_id) ON DELETE CASCADE
);

CREATE VIEW roster_presences AS
    SELECT CASE WHEN (p."type" = 'available') THEN COALESCE (p.show, 'online')
                                              ELSE 'offline' END AS presence,
           r.jid
           FROM (roster r JOIN presences p USING (presence_id));
