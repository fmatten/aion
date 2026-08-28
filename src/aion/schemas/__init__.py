# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""AION Clinical — Schema-Definitionen für Typ-Hierarchien.

Schemas sind YAML-Dateien, die mitgeliefert werden:

    aion.schemas.clinical_base       Standard-Hierarchie für klinische Events
    aion.schemas.cardiology_extension Erweiterung für Kardiologie
    aion.schemas.icu_extension       Erweiterung für Intensivmedizin

Pfad zur Schema-Datei via importlib.resources::

    from importlib.resources import files
    base_path = files('aion.schemas').joinpath('clinical_base.yaml')
"""
