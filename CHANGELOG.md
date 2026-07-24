# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-07-17

### Changed
- Group captions now run vertically up the left divider of each group by
  default, removing the caption row and shaving depth; long names elide
  to the group height. Choose Left / Bottom / Off in Customize Ribbon
- Compact redesign: ribbon height roughly halved (small buttons in up to
  three configurable rows instead of 70 px fixed-size icon buttons)
- Buttons size to their content — labels are never truncated
- Actions with submenus become dropdown buttons automatically, replacing
  the hardcoded, locale-dependent popup lists
- Flat, ArcGIS Pro-style chrome: underlined active tab, vertical
  dividers between groups, and muted group captions below each group
- Ribbon colors derive from the application palette, so dark QGIS themes
  are supported
- Workflow-based default grouping: Snapping and Annotations moved to the
  Edit tab, Bookmarks and GPS to View, Labels to Layer; the "Tools"
  catch-all tab is gone

### Added
- Favorites tab: "Frequently Used" and "Recently Used" groups built from
  tracked tool usage (recorded across QGIS, stored in the profile at
  `ribbon_toolbar/usage.json`); refreshes on Refresh Ribbon / restart
- Per-tab automatic height: two rows is the standard, sparse tabs shrink
  to one row and very dense tabs may grow up to the maximum, so the
  ribbon is only as deep as the current tab needs
- Adaptive width: groups spread across the full width when they fit and
  collapse into an overflow (») dropdown when the window is too narrow.
  "Auto rows", "Spread groups" and "Adaptive" each toggle in Customize
  Ribbon
- Editable layout: tab order, groups, per-group label style, hidden
  actions and sizing are stored as JSON in the QGIS profile
  (`ribbon_toolbar/layout.json`)
- "Customize Ribbon…" dialog (gear menu on the ribbon) with visibility
  checkboxes, reordering and global options, plus "Restore Defaults"
- "Refresh Ribbon" action to pick up toolbars from late-loading plugins
- Ribbon on/off state is remembered between sessions

### Fixed
- Cloned toolbar buttons now share the original action where possible, so
  enabled/checked state stays in sync
- Safer plugin unload when initialization failed partway

## [0.4.4] - 2026-04-28

- Fix plugin initialization to happen only after UI is ready
- Add a toggle button on the menu bar corner to easily switch between ribbon and classic UI

## [0.4.3] - 2026-04-26

- Add default toolbars to show when no toolbars are set on unload

## [0.4.2] - 2026-04-14

- Release directly to QGIS plugin repository

## [0.4.0] - 2026-04-14

- Keep active toolbars visible when disabling ribbon
- Separate selection toolbar

## [0.3.0] - 2026-04-05

- Fix return to original toolbar view
- Leave menu bar visible when ribbon is active

## [0.2.0] - 2026-04-05

- Better handling of buttons that open menus
- Load on plugin activation by default.

## [0.1.0] - 2026-04-05

### Added
- Initial release
- Microsoft Office-like ribbon interface replacing QGIS menus and toolbars
- Tabbed ribbon with groups derived from QGIS menus and toolbars
- Toggle action to switch between ribbon and classic QGIS UI
- "Tools" tab for snapping, labels, selection and annotation toolbars
- Plugin toolbars automatically collected under the Plugins tab

[Unreleased]: https://github.com/eithanwes/ribbon_toolbar/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/eithanwes/ribbon_toolbar/compare/v0.4.0...v0.4.2
[0.4.0]: https://github.com/eithanwes/ribbon_toolbar/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/eithanwes/ribbon_toolbar/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/eithanwes/ribbon_toolbar/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/eithanwes/ribbon_toolbar/releases/tag/v0.1.0
