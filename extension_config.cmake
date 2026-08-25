# This file is included by DuckDB's build system.
duckdb_extension_load(junctions
    SOURCE_DIR ${CMAKE_CURRENT_LIST_DIR}
    LOAD_TESTS
)

# `junctions_cluster` requires users to INSTALL/LOAD DuckDB's separately
# distributed `spatial` extension before calling the macro.
