# junctions

A DuckDB extension for **configurable road-junction polygonisation and clustering**.

`junctions` turns a table of road centreline geometries into junction-system polygons using a transparent SQL algorithm:

1. extract line endpoints;
2. retain coincident endpoints with at least `min_arms` incident links;
3. assign a configurable buffer per road function;
4. buffer and dissolve touching nodes;
5. split dissolved systems, take a convex hull, and calculate statistics;
6. return a stable junction ID, geometry, area, centroid, node count, and arm count.

The extension intentionally delegates geometry operations to DuckDB's battle-tested `spatial` extension. It owns the road-junction policy and configuration, not another implementation of GEOS.

## Status

This is an initial, SQL-only DuckDB extension extracted from the OpenRoads junction workflow in `Robinlovelace/criticalissues`. It currently expects British National Grid input (`geom_bng` in EPSG:27700) and a `road_function` column with OS OpenRoads values.

## Install and use

Until the extension is accepted into DuckDB Community Extensions, build it locally and load the resulting `.duckdb_extension` file. Once published, the intended interface is:

```sql
INSTALL spatial;
LOAD spatial;
INSTALL junctions FROM community;
LOAD junctions;
```

```sql
FROM junctions_cluster(
  'road_links',
  motorway_buffer := 20.0,
  a_road_buffer := 15.0,
  b_road_buffer := 10.0,
  minor_road_buffer := 10.0,
  default_buffer := 5.0,
  min_arms := 2,
  output_crs := 'EPSG:4326'
);
```

### Input contract

The named input table/view must have:

| Column | Type | Meaning |
|---|---|---|
| `geom_bng` | `GEOMETRY` | Road centreline in EPSG:27700 |
| `road_function` | `VARCHAR` | OS OpenRoads road function |

### Output contract

| Column | Meaning |
|---|---|
| `junction_id` | Deterministic ID for the current input/configuration, not backward-compatible with legacy GeoPandas IDs |
| `num_nodes` | Number of coincident endpoint nodes in the system |
| `num_arms` | Sum of endpoint degrees; see limitations below |
| `area_sqm` | Area of the BNG convex-hull polygon |
| `centroid_x`, `centroid_y` | BNG centroid coordinates |
| `geom` | Convex-hull polygon transformed to `output_crs` |

## Current limitations

- `junction_id` is deterministic for the current input and configuration, but intentionally does not preserve legacy GeoPandas IDs. Rebuilding a dataset is a data-version change.
- `num_arms` deliberately preserves the legacy endpoint-degree sum. It can over-count arms at traffic islands, dual carriageways and slip roads. A forthcoming external-link/cluster-boundary method should replace it.
- Grade separation is not yet represented; bridges and tunnels need upstream filtering or a future level-aware policy.
- The public first version is BNG/OS OpenRoads-specific to permit an exact, tested cutover. General CRS and input-schema mapping are planned once the contract is stable.

## Development

This repository uses DuckDB's [SQL extension template](https://github.com/duckdb/extension-template-sql).

```sh
make release
python test/test_integration.py
```

The integration test loads the actual locally built extension into DuckDB 1.5, loads `spatial`, and covers clustering, emitted polygon type, endpoint/arm statistics, and configurable buffer rules.

## License

MIT. See [LICENSE](LICENSE).
