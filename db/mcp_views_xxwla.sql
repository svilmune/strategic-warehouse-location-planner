-- MCP_VIEWS objects used by the warehouse agents.
-- Reconstructed from ALL_* dictionary views (the MCP user has no catalog role, so DBMS_METADATA is unavailable).
-- Storage clauses omitted. Grants for the MCP user are at the end of this file.

CREATE TABLE MCP_VIEWS.XXWLA_CANDIDATE_SITE (
  SITE_ID                         NUMBER NOT NULL
, SITE_NAME                       VARCHAR2(200 BYTE) NOT NULL
, REGION                          VARCHAR2(100 BYTE)
, SITE_COUNTRY                    VARCHAR2(60 BYTE) NOT NULL
, SITE_STATE                      VARCHAR2(60 BYTE)
, SITE_CITY                       VARCHAR2(60 BYTE)
, LATITUDE                        NUMBER NOT NULL
, LONGITUDE                       NUMBER NOT NULL
, IS_EXISTING_NODE                VARCHAR2(1 BYTE) DEFAULT 'N' NOT NULL
, ACTIVE_FLAG                     VARCHAR2(1 BYTE) DEFAULT 'Y' NOT NULL
, CATEGORY                        VARCHAR2(30 BYTE)
, RATIONALE                       VARCHAR2(2000 BYTE)
, INFRASTRUCTURE_NOTE             VARCHAR2(2000 BYTE)
, SOURCE_URL                      VARCHAR2(1000 BYTE)
, DISTANCE_FROM_COG_KM            NUMBER
, CREATED_BY_AGENT                VARCHAR2(100 BYTE)
, BUSINESS_REVIEWED               VARCHAR2(1 BYTE) DEFAULT 'N' NOT NULL
, CREATION_DATE                   DATE DEFAULT SYSDATE NOT NULL
, LAST_UPDATE_DATE                DATE DEFAULT SYSDATE NOT NULL
, CONSTRAINT XXWLA_CAND_SITE_PK PRIMARY KEY (SITE_ID)
, CONSTRAINT XXWLA_CAND_SITE_U1 UNIQUE (SITE_COUNTRY, SITE_NAME)
, CONSTRAINT XXWLA_CAND_SITE_CK1 CHECK (active_flag      IN ('Y','N'))
, CONSTRAINT XXWLA_CAND_SITE_CK2 CHECK (is_existing_node IN ('Y','N'))
, CONSTRAINT XXWLA_CAND_SITE_CK3 CHECK (business_reviewed IN ('Y','N'))
, CONSTRAINT XXWLA_CAND_SITE_CK4 CHECK (latitude  BETWEEN  -90 AND  90)
, CONSTRAINT XXWLA_CAND_SITE_CK5 CHECK (longitude BETWEEN -180 AND 180)
, CONSTRAINT XXWLA_CAND_SITE_CK6 CHECK (NOT (latitude = 0 AND longitude = 0))
, CONSTRAINT XXWLA_CAND_SITE_CK7 CHECK (category IS NULL OR category IN
                         ('EXISTING_NODE','ESTABLISHED_HUB','EMERGING_MARKET'))
);

CREATE INDEX MCP_VIEWS.XXWLA_CAND_SITE_N1 ON MCP_VIEWS.XXWLA_CANDIDATE_SITE (SITE_COUNTRY, REGION);

CREATE TABLE MCP_VIEWS.XXWLA_GEO_POSTAL_CACHE (
  GEO_COUNTRY                     VARCHAR2(60 BYTE) NOT NULL
, GEO_POSTAL_CODE                 VARCHAR2(60 BYTE) NOT NULL
, GEO_CITY                        VARCHAR2(60 BYTE)
, GEO_STATE                       VARCHAR2(60 BYTE)
, LATITUDE                        NUMBER
, LONGITUDE                       NUMBER
, RESOLUTION_LEVEL                VARCHAR2(12 BYTE) NOT NULL
, RELIABILITY                     VARCHAR2(12 BYTE)
, SOURCE_NAME                     VARCHAR2(200 BYTE)
, CITATION_URL                    VARCHAR2(1000 BYTE)
, AS_OF_DATE                      DATE
, LAST_UPDATED_DATE               DATE DEFAULT SYSDATE NOT NULL
, LAST_UPDATED_BY                 VARCHAR2(100 BYTE) DEFAULT 'GEO_AGENT' NOT NULL
, CONSTRAINT XXWLA_GEO_CACHE_PK PRIMARY KEY (GEO_COUNTRY, GEO_POSTAL_CODE)
, CONSTRAINT XXWLA_GEO_CACHE_CK1 CHECK (resolution_level IN
                         ('POSTAL','CITY','STATE','UNRESOLVED'))
, CONSTRAINT XXWLA_GEO_CACHE_CK2 CHECK (reliability IS NULL OR reliability IN
                         ('HIGH','MEDIUM','LOW','UNVERIFIED'))
, CONSTRAINT XXWLA_GEO_CACHE_CK3 CHECK (latitude  IS NULL OR
                         latitude  BETWEEN  -90 AND  90)
, CONSTRAINT XXWLA_GEO_CACHE_CK4 CHECK (longitude IS NULL OR
                         longitude BETWEEN -180 AND 180)
, CONSTRAINT XXWLA_GEO_CACHE_CK5 CHECK (NOT (latitude = 0 AND longitude = 0))
, CONSTRAINT XXWLA_GEO_CACHE_CK6 CHECK (
            resolution_level = 'UNRESOLVED'
            OR (latitude IS NOT NULL AND longitude IS NOT NULL
                AND reliability IS NOT NULL AND citation_url IS NOT NULL))
);


CREATE OR REPLACE VIEW MCP_VIEWS.XXWLA_DEMAND_V AS
SELECT  hou.name                                    AS operating_unit,
        ool.org_id                                  AS org_id,
        TRUNC(ool.actual_shipment_date,'MM')        AS period_month,
        ool.ship_from_org_id                        AS ship_from_org_id,
        mp.organization_code                        AS ship_from_org_code,
        ool.inventory_item_id                       AS inventory_item_id,
        msi.segment1                                AS item_number,
        mc.segment1                                 AS category_name,
        UPPER(TRIM(hl.country))                     AS ship_to_country,
        TRIM(hl.state)                              AS ship_to_state,
        TRIM(hl.city)                               AS ship_to_city,
        UPPER(TRIM(hl.postal_code))                 AS ship_to_postal_code,
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
        SUM(NVL(wdd.net_weight,
                NVL(msi.unit_weight,0) * NVL(wdd.shipped_quantity,0)))
                                                    AS weight_kg,
        SUM(NVL(wdd.volume,
                NVL(msi.unit_volume,0) * NVL(wdd.shipped_quantity,0)))
                                                    AS volume_m3,
        SUM(NVL(wdd.shipped_quantity,0) * NVL(ool.unit_selling_price,0))
                                                    AS amount,
        MAX(ooh.transactional_curr_code)            AS currency_code,
        CASE WHEN COUNT(wdd.net_weight) > 0 THEN 'ACTUAL'
             WHEN MAX(NVL(msi.unit_weight,0)) > 0  THEN 'ESTIMATE'
             ELSE 'NONE' END                        AS wv_source,
        COUNT(DISTINCT ool.line_id)                 AS order_line_count
  FROM  oe_order_lines_all        ool
  JOIN  oe_order_headers_all      ooh  ON ooh.header_id = ool.header_id
  JOIN  wsh_delivery_details      wdd  ON wdd.source_line_id = ool.line_id
                                      AND wdd.source_code    = 'OE'
                                      AND wdd.released_status = 'C'
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
   AND  NVL(ool.line_category_code,'ORDER') = 'ORDER'
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

CREATE OR REPLACE VIEW MCP_VIEWS.XXWLA_GEO_PENDING_V AS
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
           FROM mcp_views.xxwla_demand_v d
          WHERE d.ship_to_postal_code IS NOT NULL
         UNION ALL
         SELECT n.node_country, n.node_postal_code, n.node_city, n.node_state,
                0, 'NETWORK'
           FROM mcp_views.xxwla_network_v n
          WHERE n.node_postal_code IS NOT NULL
        ) src
  LEFT JOIN mcp_views.xxwla_geo_postal_cache c
         ON c.geo_country     = src.geo_country
        AND c.geo_postal_code = src.geo_postal_code
 WHERE  c.geo_postal_code IS NULL
    OR  c.resolution_level = 'UNRESOLVED'
 GROUP BY src.geo_country, src.geo_postal_code
 ORDER BY SUM(src.units_at_risk) DESC;

CREATE OR REPLACE VIEW MCP_VIEWS.XXWLA_NETWORK_V AS
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
  LEFT JOIN mcp_views.xxwla_geo_postal_cache c
         ON c.geo_country      = UPPER(TRIM(hla.country))
        AND c.geo_postal_code  = UPPER(TRIM(hla.postal_code))
        AND c.resolution_level <> 'UNRESOLVED'
 WHERE  TRUNC(SYSDATE) BETWEEN haou.date_from
                           AND NVL(haou.date_to, TO_DATE('31-12-4712','DD-MM-YYYY'))
   AND  mp.organization_id <> mp.master_organization_id;


-- Grants for the MCP database user (as used by the agents)
GRANT SELECT                         ON MCP_VIEWS.XXWLA_DEMAND_V         TO MCP_READER;
GRANT SELECT                         ON MCP_VIEWS.XXWLA_GEO_PENDING_V    TO MCP_READER;
GRANT SELECT                         ON MCP_VIEWS.XXWLA_NETWORK_V        TO MCP_READER;
GRANT SELECT, INSERT, UPDATE         ON MCP_VIEWS.XXWLA_GEO_POSTAL_CACHE TO MCP_READER;
GRANT SELECT, INSERT, UPDATE, DELETE ON MCP_VIEWS.XXWLA_CANDIDATE_SITE   TO MCP_READER;
