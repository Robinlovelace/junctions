"""Integration tests for the locally built junctions DuckDB extension."""

from pathlib import Path
import unittest

import duckdb


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "build/release/extension/junctions/junctions.duckdb_extension"


class JunctionsExtensionTest(unittest.TestCase):
    def setUp(self):
        if not EXTENSION.exists():
            self.skipTest("Run `make release` before the integration test")
        self.con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
        self.con.execute("INSTALL spatial; LOAD spatial")
        self.con.execute(f"LOAD '{EXTENSION}'")

    def tearDown(self):
        self.con.close()

    def test_clusters_coincident_endpoints_and_reports_stats(self):
        self.con.execute(
            """CREATE TABLE road_links(id INTEGER, road_function VARCHAR, geom_bng GEOMETRY);
            INSERT INTO road_links VALUES
                (1, 'A Road', ST_GeomFromText('LINESTRING (0 0, 10 0)')),
                (2, 'A Road', ST_GeomFromText('LINESTRING (0 0, 0 10)')),
                (3, 'Local Road', ST_GeomFromText('LINESTRING (100 0, 110 0)')),
                (4, 'Local Road', ST_GeomFromText('LINESTRING (100 0, 100 10)'));
            """
        )
        result = self.con.execute(
            """SELECT junction_id, num_nodes, num_arms, ST_GeometryType(geom)
            FROM junctions_cluster('road_links', output_crs := 'EPSG:27700')"""
        ).fetchall()
        self.assertEqual(result, [("0", 1, 2, "POLYGON"), ("1", 1, 2, "POLYGON")])

    def test_osm_adapter_nodes_interior_crossing_and_keeps_levels_separate(self):
        self.con.execute(
            """CREATE TABLE quackosm(feature_id VARCHAR, tags MAP(VARCHAR, VARCHAR), geometry GEOMETRY);
            INSERT INTO quackosm VALUES
                ('way/1', MAP {'highway': 'primary'}, ST_GeomFromText('LINESTRING (-1.5100 53.0000, -1.4900 53.0000)')),
                ('way/2', MAP {'highway': 'residential'}, ST_GeomFromText('LINESTRING (-1.5000 52.9900, -1.5000 53.0100)')),
                ('way/3', MAP {'highway': 'primary', 'bridge': 'yes'}, ST_GeomFromText('LINESTRING (-1.5100 53.0100, -1.4900 53.0100)'));
            """
        )
        result = self.con.execute(
            """SELECT level_key, num_nodes, num_arms, ST_GeometryType(geom)
            FROM junctions_from_osm(
                'quackosm', analysis_crs := 'EPSG:27700', output_crs := 'EPSG:27700'
            )"""
        ).fetchall()
        self.assertEqual(result, [(0, 1, 4, 'POLYGON')])

    def test_osm_adapter_selects_bng_for_a_uk_case_study(self):
        self.con.execute(
            """CREATE TABLE quackosm_uk(feature_id VARCHAR, tags MAP(VARCHAR, VARCHAR), geometry GEOMETRY);
            INSERT INTO quackosm_uk VALUES
                ('way/1', MAP {'highway': 'primary'}, ST_GeomFromText('LINESTRING (-1.5100 53.0000, -1.4900 53.0000)')),
                ('way/2', MAP {'highway': 'residential'}, ST_GeomFromText('LINESTRING (-1.5000 52.9900, -1.5000 53.0100)'));
            """
        )
        result = self.con.execute(
            "SELECT analysis_crs, num_arms FROM junctions_from_osm('quackosm_uk')"
        ).fetchall()
        self.assertEqual(result, [('EPSG:27700', 4)])

    def test_osm_adapter_selects_local_utm_outside_uk(self):
        self.con.execute(
            """CREATE TABLE quackosm_vancouver(feature_id VARCHAR, tags MAP(VARCHAR, VARCHAR), geometry GEOMETRY);
            INSERT INTO quackosm_vancouver VALUES
                ('way/1', MAP {'highway': 'primary'}, ST_GeomFromText('LINESTRING (-123.1100 49.2800, -123.0900 49.2800)')),
                ('way/2', MAP {'highway': 'residential'}, ST_GeomFromText('LINESTRING (-123.1000 49.2700, -123.1000 49.2900)'));
            """
        )
        result = self.con.execute(
            "SELECT analysis_crs, num_arms FROM junctions_from_osm('quackosm_vancouver')"
        ).fetchall()
        self.assertEqual(result, [('EPSG:32610', 4)])

    def test_buffer_configuration_changes_cluster_membership(self):
        self.con.execute(
            """CREATE TABLE nearby_links(id INTEGER, road_function VARCHAR, geom_bng GEOMETRY);
            INSERT INTO nearby_links VALUES
                (1, 'Local Road', ST_GeomFromText('LINESTRING (0 0, 1 0)')),
                (2, 'Local Road', ST_GeomFromText('LINESTRING (0 0, 0 1)')),
                (3, 'Local Road', ST_GeomFromText('LINESTRING (18 0, 19 0)')),
                (4, 'Local Road', ST_GeomFromText('LINESTRING (18 0, 18 1)'));
            """
        )
        separate = self.con.execute(
            "SELECT count(*) FROM junctions_cluster('nearby_links', output_crs := 'EPSG:27700')"
        ).fetchone()[0]
        merged = self.con.execute(
            """SELECT count(*) FROM junctions_cluster(
                'nearby_links', default_buffer := 10.0, output_crs := 'EPSG:27700'
            )"""
        ).fetchone()[0]
        self.assertEqual((separate, merged), (2, 1))


if __name__ == "__main__":
    unittest.main()
