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
