-- =============================================================================
-- Warehouse location agents - Oracle objects in schema MCP_VIEWS
-- Run as the MCP_VIEWS owner, in this order (later objects depend on earlier).
--   1. xxwla_geo_postal_cache   (table, agent-maintained)
--   2. xxwla_candidate_site     (table, agent-maintained)
--   3. xxwla_network_v          (view, reads the geocode cache)
--   4. xxwla_demand_v           (view)
--   5. xxwla_geo_pending_v      (view, reads demand, network and cache)
--   6. Grants to the MCP database user
-- =============================================================================

--------------------------------------------------------------------------------
-- xxwla_geo_postal_cache
-- Postal code to coordinates. Written by the geocoding agent via MERGE.
-- Reference data: a postal code has the same coordinates next year, which is
-- why this is cached rather than looked up at query time.
--------------------------------------------------------------------------------
CREATE TABLE xxwla_geo_postal_cache (
    geo_country          VARCHAR2(60)   NOT NULL,
    geo_postal_code      VARCHAR2(60)   NOT NULL,
    geo_city             VARCHAR2(60),
    geo_state            VARCHAR2(60),
    latitude             NUMBER,
    longitude            NUMBER,
    resolution_level     VARCHAR2(12)   NOT NULL,   -- POSTAL|CITY|STATE|UNRESOLVED
    reliability          VARCHAR2(12),              -- HIGH|MEDIUM|LOW|UNVERIFIED
    source_name          VARCHAR2(200),
    citation_url         VARCHAR2(1000),
    as_of_date           DATE,
    last_updated_date    DATE           DEFAULT SYSDATE NOT NULL,
    last_updated_by      VARCHAR2(100)  DEFAULT 'GEO_AGENT' NOT NULL,
    CONSTRAINT xxwla_geo_cache_pk  PRIMARY KEY (geo_country, geo_postal_code),
    CONSTRAINT xxwla_geo_cache_ck1 CHECK (resolution_level IN
                     ('POSTAL','CITY','STATE','UNRESOLVED')),
    CONSTRAINT xxwla_geo_cache_ck2 CHECK (reliability IS NULL OR reliability IN
                     ('HIGH','MEDIUM','LOW','UNVERIFIED')),
    CONSTRAINT xxwla_geo_cache_ck3 CHECK (latitude  IS NULL OR
                     latitude  BETWEEN  -90 AND  90),
    CONSTRAINT xxwla_geo_cache_ck4 CHECK (longitude IS NULL OR
                     longitude BETWEEN -180 AND 180),
    -- Null island guard: 0,0 is the classic geocoding failure signature.
    CONSTRAINT xxwla_geo_cache_ck5 CHECK (NOT (latitude = 0 AND longitude = 0)),
    -- A resolved row must carry coordinates and a citation.
    CONSTRAINT xxwla_geo_cache_ck6 CHECK (
        resolution_level = 'UNRESOLVED'
        OR (latitude IS NOT NULL AND longitude IS NOT NULL
            AND reliability IS NOT NULL AND citation_url IS NOT NULL))
);


--------------------------------------------------------------------------------
-- xxwla_candidate_site
-- Candidate metros to evaluate. Populated by the geo agent (Mode B) from
-- markets near the demand centre of gravity, then refined by the business.
-- EBS has no concept of a warehouse that does not yet exist.
--------------------------------------------------------------------------------
CREATE TABLE xxwla_candidate_site (
    site_id              NUMBER         NOT NULL,
    site_name            VARCHAR2(200)  NOT NULL,
    region               VARCHAR2(100),
    site_country         VARCHAR2(60)   NOT NULL,
    site_state           VARCHAR2(60),
    site_city            VARCHAR2(60),
    latitude             NUMBER         NOT NULL,
    longitude            NUMBER         NOT NULL,
    is_existing_node     VARCHAR2(1)    DEFAULT 'N' NOT NULL,
    active_flag          VARCHAR2(1)    DEFAULT 'Y' NOT NULL,
    -- Provenance: how this candidate came to be on the list.
    category             VARCHAR2(30),  -- EXISTING_NODE|ESTABLISHED_HUB|
                                        -- EMERGING_MARKET
    rationale            VARCHAR2(2000),
    infrastructure_note  VARCHAR2(2000),
    source_url           VARCHAR2(1000),
    distance_from_cog_km NUMBER,        -- distance from demand centre of gravity
    created_by_agent     VARCHAR2(100),
    business_reviewed    VARCHAR2(1)    DEFAULT 'N' NOT NULL,
    creation_date        DATE           DEFAULT SYSDATE NOT NULL,
    last_update_date     DATE           DEFAULT SYSDATE NOT NULL,
    CONSTRAINT xxwla_cand_site_pk  PRIMARY KEY (site_id),
    CONSTRAINT xxwla_cand_site_u1  UNIQUE (site_country, site_name),
    CONSTRAINT xxwla_cand_site_ck1 CHECK (active_flag      IN ('Y','N')),
    CONSTRAINT xxwla_cand_site_ck2 CHECK (is_existing_node IN ('Y','N')),
    CONSTRAINT xxwla_cand_site_ck3 CHECK (business_reviewed IN ('Y','N')),
    CONSTRAINT xxwla_cand_site_ck4 CHECK (latitude  BETWEEN  -90 AND  90),
    CONSTRAINT xxwla_cand_site_ck5 CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT xxwla_cand_site_ck6 CHECK (NOT (latitude = 0 AND longitude = 0)),
    CONSTRAINT xxwla_cand_site_ck7 CHECK (category IS NULL OR category IN
                     ('EXISTING_NODE','ESTABLISHED_HUB','EMERGING_MARKET'))
);

CREATE INDEX xxwla_cand_site_n1 ON xxwla_candidate_site (site_country, region);

--------------------------------------------------------------------------------
-- xxwla_network_v
-- Active inventory organisations with address and resolved coordinates.
-- Coordinates come from the geocode cache; NULL means not yet geocoded, which
-- surfaces in xxwla_geo_pending_v.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW xxwla_network_v AS
SELECT  hou.name                                AS operating_unit,
        hoi.org_information3                    AS org_id,
        mp.organization_id                      AS organization_id,
        mp.organization_code                    AS organization_code,
        haou.name                               AS organization_name,
        UPPER(TRIM(hla.country))                AS node_country,
        TRIM(hla.region_2)                      AS node_state,
        TRIM(hla.town_or_city)                  AS node_city,
        UPPER(TRIM(hla.postal_code))            AS node_postal_code,
        c.latitude                              AS latitude,
        c.longitude                             AS longitude,
        'WAREHOUSE'                             AS node_type,
        'Y'                                     AS active_flag
  FROM  mtl_parameters             mp
  JOIN  hr_all_organization_units  haou ON haou.organization_id =
                                           mp.organization_id
  JOIN  hr_locations_all           hla  ON hla.location_id = haou.location_id
  LEFT JOIN hr_organization_information hoi
         ON hoi.organization_id = mp.organization_id
        AND hoi.org_information_context = 'Accounting Information'
  LEFT JOIN hr_operating_units     hou
         ON hou.organization_id = TO_NUMBER(hoi.org_information3)
  LEFT JOIN xxwla_geo_postal_cache c
         ON c.geo_country      = UPPER(TRIM(hla.country))
        AND c.geo_postal_code  = UPPER(TRIM(hla.postal_code))
        AND c.resolution_level <> 'UNRESOLVED'
 WHERE  TRUNC(SYSDATE) BETWEEN haou.date_from
                           AND NVL(haou.date_to, TO_DATE('31-12-4712','DD-MM-YYYY'))
   -- Inventory organisations only; exclude master orgs that aren't physical
   -- stocking points.
   AND  mp.organization_id <> mp.master_organization_id;

--------------------------------------------------------------------------------
-- xxwla_demand_v
-- Shipped demand at postal x month x ship-from org x item grain.
-- Plain view over all data. Filtering by OU, period and region is applied by
-- the MCP tool's WHERE clause, not inside the view.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW xxwla_demand_v AS
SELECT  hou.name                                    AS operating_unit,
        ool.org_id                                  AS org_id,
        TRUNC(ool.actual_shipment_date,'MM')              AS period_month,
        ool.ship_from_org_id                        AS ship_from_org_id,
        mp.organization_code                        AS ship_from_org_code,
        ool.inventory_item_id                       AS inventory_item_id,
        msi.segment1                                AS item_number,
        mc.segment1                                 AS category_name,
        UPPER(TRIM(hl.country))                     AS ship_to_country,
        TRIM(hl.state)                              AS ship_to_state,
        TRIM(hl.city)                               AS ship_to_city,
        UPPER(TRIM(hl.postal_code))                 AS ship_to_postal_code,
        -- US census-style region grouping. Extend or replace with your own
        -- mapping table if the business uses different territories.
        CASE
          WHEN UPPER(TRIM(hl.country)) <> 'US' THEN 'NON-US'
          WHEN hl.state IN ('CT','ME','MA','NH','RI','VT','NJ','NY','PA')
               THEN 'Northeast'
          WHEN hl.state IN ('IL','IN','MI','OH','WI','IA','KS','MN','MO',
                            'NE','ND','SD')
               THEN 'Midwest'
          WHEN hl.state IN ('DE','FL','GA','MD','NC','SC','VA','DC','WV',
                            'AL','KY','MS','TN')
               THEN 'Southeast'
          WHEN hl.state IN ('AR','LA','OK','TX','AZ','NM')
               THEN 'Southwest'
          WHEN hl.state IN ('CO','ID','MT','UT','NV','WY','AK','CA','HI','OR','WA')
               THEN 'West'
          ELSE 'Unmapped'
        END                                         AS region,
        SUM(NVL(wdd.shipped_quantity,0))            AS units,
        MAX(ool.order_quantity_uom)                 AS uom_code,
        -- Actual shipped weight preferred; item-master estimate as fallback.
        SUM(NVL(wdd.net_weight,
                NVL(msi.unit_weight,0) * NVL(wdd.shipped_quantity,0)))
                                                    AS weight_kg,
        SUM(NVL(wdd.volume,
                NVL(msi.unit_volume,0) * NVL(wdd.shipped_quantity,0)))
                                                    AS volume_m3,
        SUM(NVL(wdd.shipped_quantity,0) * NVL(ool.unit_selling_price,0))
                                                    AS amount,
        MAX(ooh.transactional_curr_code)            AS currency_code,
        -- Records whether weight/volume came from the shipment or was derived.
        CASE WHEN COUNT(wdd.net_weight) > 0 THEN 'ACTUAL'
             WHEN MAX(NVL(msi.unit_weight,0)) > 0  THEN 'ESTIMATE'
             ELSE 'NONE' END                        AS wv_source,
        COUNT(DISTINCT ool.line_id)                 AS order_line_count
  FROM  oe_order_lines_all        ool
  JOIN  oe_order_headers_all      ooh  ON ooh.header_id = ool.header_id
  JOIN  wsh_delivery_details      wdd  ON wdd.source_line_id = ool.line_id
                                      AND wdd.source_code    = 'OE'
                                      AND wdd.released_status = 'C'   -- shipped
  JOIN  hz_cust_site_uses_all     hcsu ON hcsu.site_use_id = ool.ship_to_org_id
                                      AND hcsu.site_use_code = 'SHIP_TO'
                                      AND hcsu.status = 'A'
  JOIN  hz_cust_acct_sites_all    hcas ON hcas.cust_acct_site_id =
                                          hcsu.cust_acct_site_id
  JOIN  hz_party_sites            hps  ON hps.party_site_id = hcas.party_site_id
  JOIN  hz_locations              hl   ON hl.location_id = hps.location_id
  JOIN  mtl_system_items_b        msi  ON msi.inventory_item_id =
                                          ool.inventory_item_id
                                      AND msi.organization_id =
                                          ool.ship_from_org_id
  JOIN  mtl_parameters            mp   ON mp.organization_id =
                                          ool.ship_from_org_id
  JOIN  hr_operating_units        hou  ON hou.organization_id = ool.org_id
  LEFT JOIN mtl_item_categories   mic  ON mic.inventory_item_id =
                                          ool.inventory_item_id
                                      AND mic.organization_id =
                                          ool.ship_from_org_id
  LEFT JOIN mtl_categories_b      mc   ON mc.category_id = mic.category_id
 WHERE  ool.cancelled_flag  = 'N'
   AND  ool.open_flag      IN ('N','Y')
   AND  NVL(ool.line_category_code,'ORDER') = 'ORDER'   -- excludes RMA lines
   AND  ool.actual_shipment_date IS NOT NULL
 GROUP BY hou.name, ool.org_id, TRUNC(ool.actual_shipment_date,'MM'),
        ool.ship_from_org_id, mp.organization_code,
        ool.inventory_item_id, msi.segment1, mc.segment1,
        UPPER(TRIM(hl.country)), TRIM(hl.state), TRIM(hl.city),
        UPPER(TRIM(hl.postal_code)),
        CASE
          WHEN UPPER(TRIM(hl.country)) <> 'US' THEN 'NON-US'
          WHEN hl.state IN ('CT','ME','MA','NH','RI','VT','NJ','NY','PA')
               THEN 'Northeast'
          WHEN hl.state IN ('IL','IN','MI','OH','WI','IA','KS','MN','MO',
                            'NE','ND','SD')
               THEN 'Midwest'
          WHEN hl.state IN ('DE','FL','GA','MD','NC','SC','VA','DC','WV',
                            'AL','KY','MS','TN')
               THEN 'Southeast'
          WHEN hl.state IN ('AR','LA','OK','TX','AZ','NM')
               THEN 'Southwest'
          WHEN hl.state IN ('CO','ID','MT','UT','NV','WY','AK','CA','HI','OR','WA')
               THEN 'West'
          ELSE 'Unmapped'
        END;

--------------------------------------------------------------------------------
-- Pending queue: postal codes in demand or network but not yet geocoded,
-- ordered by volume at risk. This replaces pending_geocodes.py.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW xxwla_geo_pending_v AS
SELECT  src.geo_country,
        src.geo_postal_code,
        MAX(src.geo_city)           AS geo_city,
        MAX(src.geo_state)          AS geo_state,
        SUM(src.units_at_risk)      AS units_at_risk,
        MAX(src.source_object)      AS seen_in
  FROM  (
         SELECT d.ship_to_country     AS geo_country,
                d.ship_to_postal_code AS geo_postal_code,
                d.ship_to_city        AS geo_city,
                d.ship_to_state       AS geo_state,
                d.units               AS units_at_risk,
                'DEMAND'              AS source_object
           FROM xxwla_demand_v d
          WHERE d.ship_to_postal_code IS NOT NULL
         UNION ALL
         -- Network rows carry zero units but MUST be geocoded: an existing
         -- warehouse without coordinates is invisible to the overlap test.
         SELECT n.node_country, n.node_postal_code, n.node_city, n.node_state,
                0, 'NETWORK'
           FROM xxwla_network_v n
          WHERE n.node_postal_code IS NOT NULL
        ) src
  LEFT JOIN xxwla_geo_postal_cache c
         ON c.geo_country     = src.geo_country
        AND c.geo_postal_code = src.geo_postal_code
 WHERE  c.geo_postal_code IS NULL
    OR  c.resolution_level = 'UNRESOLVED'
 GROUP BY src.geo_country, src.geo_postal_code
 ORDER BY SUM(src.units_at_risk) DESC;

-- -----------------------------------------------------------------------------
-- Grants for the MCP database user. No DELETE on the geocode cache: the
-- database itself enforces that geocodes are never removed.
-- -----------------------------------------------------------------------------
GRANT SELECT                         ON xxwla_demand_v         TO mcp_reader;
GRANT SELECT                         ON xxwla_network_v        TO mcp_reader;
GRANT SELECT                         ON xxwla_geo_pending_v    TO mcp_reader;
GRANT SELECT, INSERT, UPDATE         ON xxwla_geo_postal_cache TO mcp_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON xxwla_candidate_site   TO mcp_reader;
