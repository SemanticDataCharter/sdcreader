# Changelog

Versions carry the leading 4 of the SDC4 reference model: an addition to what the reader exposes is a minor version, a
fix a patch, and the major changes only when the reference model does.

## 4.0.0 (2026-10-09)

The loader and model reader that four projection writers carried as identical copies (`sdc_cdif`, `sdc_dcat3_us`,
`sdc_dcat3_ap`, `sdc_healthdcat_ap`), made one package with the same API:
`ModelPackage`, `load_package`, `fetch_package`, `read_model`, `read_header`, `enumeration_iri`, `Model`, `Component`,
`Leaf`, `Code`, `PackageError`, and the type and predicate constants.
