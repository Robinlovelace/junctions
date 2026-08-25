"""Reproducible case study: raw OSM roads and merged junctions around the Parkinson Building, Leeds.

Builds a 200 m buffer around the Parkinson Building (University of Leeds),
downloads OpenStreetMap roads with QuackOSM, clips them to the buffer, merges
them into junction polygons with the `junctions` DuckDB extension, and renders
a figure.

Dependencies:
    duckdb (>= 1.5.3), quackosm, shapely, matplotlib

Run from the repository root after building the extension:

    make release
    python examples/parkinson_leeds.py
"""

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
import shapely.wkt
from shapely.geometry.base import BaseGeometry

import quackosm as qosm

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "build/release/extension/junctions/junctions.duckdb_extension"
OUTPUT = ROOT / "docs/figures/parkinson-leeds-junctions.png"
OSM_DB = ROOT / "examples/parkinson_leeds_osm.duckdb"

CENTRE_LON, CENTRE_LAT = -1.5527068, 53.8078043  # Parkinson Building, University of Leeds

HIGHWAY_COLORS = {
    "motorway": "#8a1c1c",
    "trunk": "#b03a2e",
    "primary": "#c0392b",
    "secondary": "#d68910",
    "tertiary": "#f1c40f",
    "unclassified": "#5d6d7e",
    "residential": "#85929e",
    "service": "#aeb6bf",
    "footway": "#ccd1d9",
    "steps": "#ccd1d9",
    "cycleway": "#27ae60",
    "path": "#ccd1d9",
}
DEFAULT_COLOR = "#bdc3c7"


def build_buffer(con: duckdb.DuckDBPyConnection) -> str:
    """Return a 200 m circle around the centre as a WGS84 polygon WKT string."""
    return con.execute(
        """
        SELECT ST_AsText(ST_Transform(
            ST_Buffer(
                ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:27700', always_xy := true),
                200
            ),
            'EPSG:27700', 'EPSG:4326', always_xy := true
        ))
        """,
        [CENTRE_LON, CENTRE_LAT],
    ).fetchone()[0]


def extract_osm(buffer: BaseGeometry) -> Path:
    """Download highway features in the buffer with QuackOSM and return the DB path."""
    if OSM_DB.exists():
        OSM_DB.unlink()
    return qosm.convert_pbf_to_duckdb(
        "https://download.geofabrik.de/europe/united-kingdom/england/west-yorkshire-latest.osm.pbf",
        result_file_path=OSM_DB,
        duckdb_table_name="quackosm",
        tags_filter={"highway": True},
        keep_all_tags=True,
        explode_tags=False,
        geometry_filter=buffer,
        verbosity_mode="silent",
    )


def clip_roads(con: duckdb.DuckDBPyConnection, buffer_wkt: str) -> None:
    """Clip QuackOSM ways to the buffer, dumping multi-parts into linestrings."""
    con.execute(f"ATTACH '{OSM_DB}' AS osm (READ_ONLY)")
    con.execute("CREATE TEMP TABLE study_buffer AS SELECT ST_GeomFromText(?) AS geom", [buffer_wkt])
    con.execute(
        """
        CREATE TEMP TABLE roads_clipped AS
        SELECT
            q.feature_id,
            q.tags,
            d.geom AS geometry
        FROM osm.quackosm q, study_buffer b, UNNEST(ST_Dump(ST_Intersection(q.geometry, b.geom))) AS u(d)
        WHERE starts_with(q.feature_id, 'way/')
          AND q.tags['highway'] IS NOT NULL
          AND ST_GeometryType(q.geometry) = 'LINESTRING'
          AND ST_Intersects(q.geometry, b.geom)
          AND ST_GeometryType(d.geom) = 'LINESTRING'
        """
    )


def render(con: duckdb.DuckDBPyConnection) -> None:
    roads = con.execute(
        """
        SELECT tags['highway'] AS highway,
               ST_AsText(ST_Transform(geometry, 'EPSG:4326', 'EPSG:27700', always_xy := true)) AS wkt
        FROM roads_clipped
        """
    ).fetchall()
    roads = [(h, shapely.wkt.loads(w)) for h, w in roads]

    junctions = con.execute(
        """
        SELECT ST_AsText(ST_Transform(geom, 'EPSG:4326', 'EPSG:27700', always_xy := true)) AS wkt
        FROM junctions_from_osm('roads_clipped', output_crs := 'EPSG:4326')
        """
    ).fetchall()
    junctions = [shapely.wkt.loads(w) for w, in junctions]

    centre = con.execute(
        """
        SELECT ST_X(p), ST_Y(p) FROM (
            SELECT ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:27700', always_xy := true) AS p
        )
        """,
        [CENTRE_LON, CENTRE_LAT],
    ).fetchone()

    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=110)
    ax.add_patch(
        Circle((centre[0], centre[1]), 200, facecolor="#f4f6f7", edgecolor="#95a5a6",
               linestyle="--", linewidth=1.0, zorder=1)
    )

    for highway, geom in roads:
        color = HIGHWAY_COLORS.get(highway, DEFAULT_COLOR)
        width = 1.7 if highway in ("primary", "secondary", "tertiary", "unclassified", "residential") else 1.0
        lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        for line in lines:
            ax.plot(*line.xy, color=color, linewidth=width, zorder=2, solid_capstyle="round")

    for geom in junctions:
        ax.fill(*geom.exterior.xy, facecolor="#f6c453", edgecolor="#d68910",
                linewidth=1.1, alpha=0.55, zorder=3)

    ax.plot(centre[0], centre[1], marker="*", markersize=18, color="#c0392b", zorder=4,
            markeredgecolor="white", markeredgewidth=0.8)

    ax.set_aspect("equal")
    ax.set_xlabel("Easting (m, EPSG:27700)")
    ax.set_ylabel("Northing (m, EPSG:27700)")
    ax.set_title("Raw OSM roads and merged junctions around the Parkinson Building, University of Leeds", fontsize=11)
    ax.grid(True, color="#ecf0f1", linewidth=0.5, zorder=0)
    ax.ticklabel_format(style="plain")

    handles, labels = [], []
    for name, color in [("footway / steps", "#ccd1d9"), ("service", "#aeb6bf"),
                        ("residential", "#85929e"), ("tertiary", "#f1c40f"), ("cycleway", "#27ae60")]:
        handles.append(Line2D([], [], color=color, linewidth=2))
        labels.append(name)
    handles.append(Line2D([], [], color="#d68910", linewidth=2))
    labels.append("junction polygon")
    handles.append(Line2D([], [], marker="*", color="#c0392b", linestyle="", markersize=12))
    labels.append("Parkinson Building")
    ax.legend(handles, labels, loc="upper left", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(OUTPUT, dpi=150)
    print(f"wrote {OUTPUT}")


def main() -> None:
    con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
    con.execute("INSTALL spatial; LOAD spatial")
    con.execute(f"LOAD '{EXTENSION}'")

    buffer_wkt = build_buffer(con)
    extract_osm(shapely.wkt.loads(buffer_wkt))
    clip_roads(con, buffer_wkt)
    render(con)
    con.close()


if __name__ == "__main__":
    main()
