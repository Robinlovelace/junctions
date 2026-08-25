#define DUCKDB_EXTENSION_MAIN

#include "junctions_extension.hpp"
#include "duckdb.hpp"
#include "duckdb/catalog/default/default_functions.hpp"
#include "duckdb/catalog/default/default_table_functions.hpp"
#include "duckdb/main/extension/extension_loader.hpp"

namespace duckdb {

// The spatial operations deliberately remain SQL macros. DuckDB Spatial owns
// GEOS-backed geometry operations; this extension owns the reproducible,
// configurable road-junction clustering policy built from those operations.
static const DefaultTableMacro JUNCTIONS_TABLE_MACROS[] = {
    {DEFAULT_SCHEMA,
     "junctions_cluster",
     {"table_name", nullptr},
     {{"motorway_buffer", "20.0"},
      {"a_road_buffer", "15.0"},
      {"b_road_buffer", "10.0"},
      {"minor_road_buffer", "10.0"},
      {"default_buffer", "5.0"},
      {"min_arms", "2"},
      {"output_crs", "'EPSG:4326'"},
      {nullptr, nullptr}},
     R"(
WITH points AS (
    SELECT ST_StartPoint(geom_bng) AS pt, road_function
    FROM query_table(table_name)
    UNION ALL
    SELECT ST_EndPoint(geom_bng) AS pt, road_function
    FROM query_table(table_name)
), nodes AS (
    SELECT
        pt,
        count(*)::BIGINT AS num_arms,
        min(CASE
            WHEN road_function = 'Motorway' THEN motorway_buffer
            WHEN road_function = 'A Road' THEN a_road_buffer
            WHEN road_function = 'B Road' THEN b_road_buffer
            WHEN road_function = 'Minor Road' THEN minor_road_buffer
            ELSE default_buffer
        END)::DOUBLE AS node_buffer
    FROM points
    GROUP BY pt
    HAVING count(*) >= min_arms
), dissolved AS (
    SELECT ST_Union_Agg(ST_Buffer(pt, node_buffer, 8)) AS geom
    FROM nodes
), components AS (
    SELECT
        row_number() OVER (
            ORDER BY ST_X(ST_Centroid(d.geom)), ST_Y(ST_Centroid(d.geom))
        ) - 1 AS junction_id,
        ST_ConvexHull(d.geom) AS geom_bng
    FROM dissolved, UNNEST(ST_Dump(geom)) AS u(d)
), stats AS (
    SELECT
        c.junction_id,
        count(*)::BIGINT AS num_nodes,
        sum(n.num_arms)::BIGINT AS num_arms
    FROM components c
    JOIN nodes n ON ST_Intersects(c.geom_bng, n.pt)
    GROUP BY c.junction_id
)
SELECT
    c.junction_id::VARCHAR AS junction_id,
    s.num_nodes,
    s.num_arms,
    ST_Area(c.geom_bng) AS area_sqm,
    ST_X(ST_Centroid(c.geom_bng)) AS centroid_x,
    ST_Y(ST_Centroid(c.geom_bng)) AS centroid_y,
    ST_Transform(c.geom_bng, 'EPSG:27700', output_crs, always_xy := true) AS geom
FROM components c
JOIN stats s USING (junction_id)
ORDER BY c.junction_id
)"},
    {DEFAULT_SCHEMA,
     "junctions_from_osm",
     {"table_name", nullptr},
     {{"analysis_crs", "'EPSG:27700'"},
      {"output_crs", "'EPSG:4326'"},
      {"motorway_buffer", "20.0"},
      {"strategic_buffer", "15.0"},
      {"main_road_buffer", "10.0"},
      {"local_road_buffer", "5.0"},
      {"min_arms", "2"},
      {nullptr, nullptr}},
     R"(
WITH roads AS (
    SELECT
        feature_id AS source_id,
        tags['highway'] AS highway,
        CASE
            WHEN try_cast(tags['layer'] AS INTEGER) IS NOT NULL THEN try_cast(tags['layer'] AS INTEGER)
            WHEN tags['bridge'] IS NOT NULL AND tags['bridge'] != 'no' THEN 1
            WHEN tags['tunnel'] IS NOT NULL AND tags['tunnel'] != 'no' THEN -1
            ELSE 0
        END AS level_key,
        ST_Transform(geometry, 'EPSG:4326', analysis_crs, always_xy := true) AS geom
    FROM query_table(table_name)
    WHERE starts_with(feature_id, 'way/')
      AND tags['highway'] IS NOT NULL
      AND ST_GeometryType(geometry) = 'LINESTRING'
), noded AS (
    SELECT level_key, ST_Node(ST_Union_Agg(geom)) AS geom
    FROM roads
    GROUP BY level_key
), segments AS (
    SELECT level_key, d.geom AS geom
    FROM noded, UNNEST(ST_Dump(geom)) AS u(d)
), points AS (
    SELECT level_key, ST_StartPoint(geom) AS pt FROM segments
    UNION ALL
    SELECT level_key, ST_EndPoint(geom) AS pt FROM segments
), raw_nodes AS (
    SELECT level_key, pt, count(*)::BIGINT AS num_arms
    FROM points
    GROUP BY level_key, pt
    HAVING count(*) >= min_arms
), nodes AS (
    SELECT
        n.level_key,
        n.pt,
        n.num_arms,
        min(CASE
            WHEN r.highway IN ('motorway', 'motorway_link') THEN motorway_buffer
            WHEN r.highway IN ('trunk', 'trunk_link', 'primary', 'primary_link') THEN strategic_buffer
            WHEN r.highway IN ('secondary', 'secondary_link', 'tertiary', 'tertiary_link') THEN main_road_buffer
            ELSE local_road_buffer
        END)::DOUBLE AS node_buffer
    FROM raw_nodes n
    JOIN roads r ON n.level_key = r.level_key AND ST_DWithin(r.geom, n.pt, 0.01)
    GROUP BY n.level_key, n.pt, n.num_arms
), dissolved AS (
    SELECT level_key, ST_Union_Agg(ST_Buffer(pt, node_buffer, 8)) AS geom
    FROM nodes
    GROUP BY level_key
), components AS (
    SELECT level_key, ST_ConvexHull(d.geom) AS geom_analysis
    FROM dissolved, UNNEST(ST_Dump(geom)) AS u(d)
), numbered AS (
    SELECT
        row_number() OVER (
            ORDER BY level_key, ST_X(ST_Centroid(geom_analysis)), ST_Y(ST_Centroid(geom_analysis))
        ) - 1 AS junction_id,
        *
    FROM components
), stats AS (
    SELECT
        c.junction_id,
        count(*)::BIGINT AS num_nodes,
        sum(n.num_arms)::BIGINT AS num_arms
    FROM numbered c
    JOIN nodes n ON c.level_key = n.level_key AND ST_Intersects(c.geom_analysis, n.pt)
    GROUP BY c.junction_id
)
SELECT
    c.junction_id::VARCHAR AS junction_id,
    c.level_key,
    s.num_nodes,
    s.num_arms,
    ST_Area(c.geom_analysis) AS area_sqm,
    ST_X(ST_Centroid(c.geom_analysis)) AS centroid_x,
    ST_Y(ST_Centroid(c.geom_analysis)) AS centroid_y,
    ST_Transform(c.geom_analysis, analysis_crs, output_crs, always_xy := true) AS geom
FROM numbered c
JOIN stats s USING (junction_id)
ORDER BY c.junction_id
)"},
    {nullptr, nullptr, {nullptr}, {{nullptr, nullptr}}, nullptr}};

static void LoadInternal(ExtensionLoader &loader) {
    for (idx_t index = 0; JUNCTIONS_TABLE_MACROS[index].name != nullptr; index++) {
        auto info = DefaultTableFunctionGenerator::CreateTableMacroInfo(JUNCTIONS_TABLE_MACROS[index]);
        loader.RegisterFunction(*info);
    }
}

void JunctionsExtension::Load(ExtensionLoader &loader) {
    LoadInternal(loader);
}

std::string JunctionsExtension::Name() {
    return "junctions";
}

std::string JunctionsExtension::Version() const {
#ifdef EXT_VERSION_JUNCTIONS
    return EXT_VERSION_JUNCTIONS;
#else
    return "";
#endif
}

} // namespace duckdb

extern "C" {

DUCKDB_CPP_EXTENSION_ENTRY(junctions, loader) {
    duckdb::LoadInternal(loader);
}

} // extern "C"

#ifndef DUCKDB_EXTENSION_MAIN
#error DUCKDB_EXTENSION_MAIN not defined
#endif
