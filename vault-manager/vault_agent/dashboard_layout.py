"""Render the default dashboard-first vault navigation shells."""

from __future__ import annotations

from pathlib import Path

from .base_hierarchy import _base_block, _dashboard_frontmatter
from .paths import VaultPaths


GENERATED_START = "<!-- pi-vault:generated:start -->"
GENERATED_END = "<!-- pi-vault:generated:end -->"


def dashboard_shell_contents(paths: VaultPaths) -> dict[str, str]:
    dashboards = paths.dashboards_dir
    content = paths.content_dirs
    return {
        (dashboards / "Home.md").as_posix(): _home_dashboard(paths),
        (dashboards / "Domains.md").as_posix(): _property_dashboard(
            "Domains", "Vault notes grouped by approved domain.", "domain"
        ),
        (dashboards / "Projects.md").as_posix(): _typed_dashboard(
            "Projects", "Projects across every domain and physical folder.", "project"
        ),
        (dashboards / "People.md").as_posix(): _people_dashboard(paths),
        (dashboards / "Organizations.md").as_posix(): _typed_dashboard(
            "Organizations", "Organizations represented anywhere in the vault.", "organization"
        ),
        (dashboards / "Sources.md").as_posix(): _sources_dashboard(),
        (dashboards / "Vault Maintenance.md").as_posix(): _maintenance_dashboard(paths),
        (content["contacts"] / "Contacts.md").as_posix(): _person_collection(
            "Contacts", "Direct contacts and conversation participants.", "Contacts"
        ),
        (content["authors"] / "Authors.md").as_posix(): _person_collection(
            "Authors", "Authors, thinkers, and other people cited as sources.", "Authors"
        ),
        (content["organizations"] / "Organizations.md").as_posix(): _typed_dashboard(
            "Organizations", "Organizations the user is involved in or tracks.", "organization"
        ),
        (content["work"] / "Work.md").as_posix(): _domain_dashboard("Work", "work"),
        (content["administrative"] / "Administrative.md").as_posix(): _administrative_dashboard(
            paths
        ),
        (content["health"] / "Health.md").as_posix(): _domain_dashboard("Health", "health"),
        (content["home"] / "Home.md").as_posix(): _domain_dashboard("Home", "household"),
        (content["finance"] / "Finance.md").as_posix(): _domain_dashboard("Finance", "finance"),
        (content["travel"] / "Travel.md").as_posix(): _domain_dashboard("Travel", "travel"),
        (content["administrative_general"] / "General.md").as_posix(): _domain_dashboard(
            "General Administration", "administration"
        ),
        (content["thoughts"] / "Thoughts.md").as_posix(): _thoughts_dashboard(paths),
        (content["sources"] / "Sources.md").as_posix(): _sources_dashboard(),
    }


def _managed(body: str) -> str:
    return f"{GENERATED_START}\n\n{body.rstrip()}\n\n{GENERATED_END}"


def _note(title: str, description: str, generated: str, *, domain: str = "meta") -> str:
    return f"""{_dashboard_frontmatter(domain=domain)}

# {title}

> [!abstract] {title}
> {description}

## Orientation

Add durable context, priorities, and curated links here. pi-vault preserves this section.

{_managed(generated)}
"""


def _home_dashboard(paths: VaultPaths) -> str:
    dashboard = paths.dashboards_dir.as_posix()
    links = "\n".join(
        f"- [[{dashboard}/{name}|{name}]]"
        for name in ("Domains", "Projects", "People", "Organizations", "Sources", "Vault Maintenance")
    )
    recent = _base_block(
        filters=[
            'file.ext == "md"',
            f'!file.path.startsWith("{paths.system_dir.as_posix()}")',
        ],
        views=[
            {
                "type": "table",
                "name": "Recently Updated",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "domain", "status", "file.mtime"],
            }
        ],
    )
    active = _base_block(
        filters=['file.ext == "md"', 'type == "project"', 'status == "active"'],
        views=[
            {
                "type": "cards",
                "name": "Active Projects",
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "domain", "parent", "cover"],
            }
        ],
    )
    return _note(
        "Home",
        "Primary entry point for capture, navigation, active work, and vault health.",
        f"## Navigate\n\n{links}\n\n## Active Projects\n\n{active}\n\n## Recently Updated\n\n{recent}",
    )


def _property_dashboard(title: str, description: str, property_name: str) -> str:
    block = _base_block(
        filters=['file.ext == "md"', f'{property_name} != ""', 'type != "system"'],
        views=[
            {
                "type": "table",
                "name": title,
                "group_by": (property_name, "ASC"),
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "type", "status", "domain", "parent"],
            }
        ],
    )
    return _note(title, description, f"## {title}\n\n{block}")


def _typed_dashboard(title: str, description: str, note_type: str) -> str:
    block = _base_block(
        filters=['file.ext == "md"', f'type == "{note_type}"'],
        views=[
            {
                "type": "table",
                "name": title,
                "group_by": ("domain", "ASC"),
                "sort": [("status", "ASC"), ("file.name", "ASC")],
                "order": ["file.name", "status", "domain", "parent", "related"],
            }
        ],
    )
    return _note(title, description, f"## {title}\n\n{block}")


def _people_dashboard(paths: VaultPaths) -> str:
    contacts = (paths.content_dirs["contacts"] / "Contacts.md").as_posix()
    authors = (paths.content_dirs["authors"] / "Authors.md").as_posix()
    block = _base_block(
        filters=['file.ext == "md"', 'type == "person"'],
        views=[
            {
                "type": "table",
                "name": "All People",
                "group_by": ("parent", "ASC"),
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "parent", "domain", "related"],
            }
        ],
    )
    return _note(
        "People",
        "People are stored once and may appear in both contact and author views.",
        f"## Collections\n\n- [[{contacts}|Contacts]]\n- [[{authors}|Authors]]\n\n## All People\n\n{block}",
    )


def _person_collection(title: str, description: str, hub: str) -> str:
    filters = ['file.ext == "md"', 'type == "person"']
    if hub == "Contacts":
        filters.append('parent == "[[Contacts]]"')
    else:
        filters.append('(parent == "[[Authors]]" or related.contains("[[Authors]]"))')
    block = _base_block(
        filters=filters,
        views=[
            {
                "type": "table",
                "name": title,
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "domain", "parent", "related"],
            }
        ],
    )
    return _note(title, description, f"## {title}\n\n{block}", domain="personal")


def _sources_dashboard() -> str:
    block = _base_block(
        filters=['file.ext == "md"', '(type == "source" or source_kind != "")'],
        views=[
            {
                "type": "table",
                "name": "Sources",
                "group_by": ("source_kind", "ASC"),
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "source_kind", "domain", "parent", "status"],
            }
        ],
    )
    return _note("Sources", "Books, articles, reports, recordings, and other source notes.", f"## Sources\n\n{block}")


def _domain_dashboard(title: str, domain: str) -> str:
    block = _base_block(
        filters=['file.ext == "md"', f'domain == "{domain}"'],
        views=[
            {
                "type": "table",
                "name": title,
                "group_by": ("parent", "ASC"),
                "sort": [("status", "ASC"), ("file.name", "ASC")],
                "order": ["file.name", "type", "status", "parent", "related"],
            }
        ],
    )
    return _note(title, f"{title} notes and projects.", f"## {title}\n\n{block}", domain=domain)


def _administrative_dashboard(paths: VaultPaths) -> str:
    content = paths.content_dirs
    links = "\n".join(
        f"- [[{content[key].as_posix()}/{label}|{label}]]"
        for key, label in (
            ("health", "Health"),
            ("home", "Home"),
            ("finance", "Finance"),
            ("travel", "Travel"),
            ("administrative_general", "General"),
        )
    )
    block = _base_block(
        filters=[
            'file.ext == "md"',
            '(domain == "administration" or domain == "health" or domain == "household" or domain == "finance" or domain == "travel")',
        ],
        views=[
            {
                "type": "table",
                "name": "Administrative",
                "group_by": ("domain", "ASC"),
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "type", "status", "domain", "parent"],
            }
        ],
    )
    return _note("Administrative", "Health, home, finance, travel, and general administration.", f"## Areas\n\n{links}\n\n## All Administrative Notes\n\n{block}", domain="administration")


def _thoughts_dashboard(paths: VaultPaths) -> str:
    root = paths.content_dirs["thoughts"].as_posix()
    block = _base_block(
        filters=['file.ext == "md"', f'file.path.startsWith("{root}")'],
        views=[
            {
                "type": "table",
                "name": "Thoughts",
                "group_by": ("domain", "ASC"),
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "domain", "parent", "file.mtime"],
            }
        ],
    )
    return _note("Thoughts", "Reflections, research, ideas, daily notes, and general knowledge.", f"## Thoughts\n\n{block}")


def _maintenance_dashboard(paths: VaultPaths) -> str:
    missing = _base_block(
        filters=[
            'file.ext == "md"',
            'type != "system"',
            f'!file.path.startsWith("{paths.system_dir.as_posix()}")',
            '(type == "" or domain == "")',
        ],
        views=[
            {
                "type": "table",
                "name": "Needs Metadata",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "domain", "parent", "file.mtime"],
            }
        ],
    )
    inbox = _base_block(
        filters=['file.ext == "md"', f'file.path.startsWith("{paths.inbox_dir.as_posix()}")'],
        views=[
            {
                "type": "table",
                "name": "Inbox",
                "sort": [("file.ctime", "ASC")],
                "order": ["file.name", "type", "domain", "status", "file.ctime"],
            }
        ],
    )
    return _note(
        "Vault Maintenance",
        "Operational surface for inbox work, metadata gaps, validation, and pending review.",
        f"## Inbox\n\n{inbox}\n\n## Needs Metadata\n\n{missing}\n\n## Review\n\n- [[{paths.review_dir.as_posix()}/proposed-changes|Pending proposals]]\n- [[{paths.review_dir.as_posix()}/needs-review|Validation review]]",
    )


def dashboard_directories(paths: VaultPaths) -> tuple[Path, ...]:
    return (paths.dashboards_dir, *paths.content_dirs.values())
