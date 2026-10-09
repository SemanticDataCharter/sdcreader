"""sdcreader: read a published Semantic Data Charter model's package for projection into other standards.

A projection (CDIF, DCAT-US, DCAT-AP, HealthDCAT-AP, ...) describes a model's governed data records in another
standard's terms. What it describes is the model's package: the JSON-LD with the components and their semantic
links, the immutable schema the records are validated against, the public catalog record, the published schema
versions. This package loads or fetches that evidence and reads it into one shape every projection shares: the
record tree, its leaves in document order, the enumerated values with the codes the schema annotates them with,
and the model's own Dublin Core with SDCStudio's field defaults read as unset. It knows nothing about any
projection.
"""
from .model import (CLOSE, DC_DEFAULTS, EXACT, HAS_UNIT, IDENTIFIER, LEAF_TYPES, NUMERIC_TYPES, PUBLISHER, QUANTIFIED_TYPES, SEE_ALSO,
                    SOURCE, Code, Component, Leaf, Model, enumeration_iri, read_header, read_model)
from .package import DEFAULT_HOST, ModelPackage, PackageError, fetch_package, load_package

__version__ = "4.0.0"
__all__ = ["ModelPackage", "PackageError", "DEFAULT_HOST", "load_package", "fetch_package", "read_model", "read_header", "enumeration_iri",
           "Model", "Component", "Leaf", "Code", "LEAF_TYPES", "NUMERIC_TYPES", "QUANTIFIED_TYPES", "DC_DEFAULTS", "IDENTIFIER", "SOURCE",
           "PUBLISHER", "EXACT", "CLOSE", "SEE_ALSO", "HAS_UNIT", "__version__"]
