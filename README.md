# 7Stars — Seven Stars Halls (قاعات سفن ستارز)

Odoo.sh repository for the Seven Stars Halls booking system.

- **Client:** Seven Stars Halls — Al Walaja, Bethlehem
- **Implementer:** Al Shayeb
- **Platform:** Odoo 19 Enterprise (version is set in Odoo.sh project settings, not here)
- **Odoo.sh project:** `mohammadnawawra2003-7stars`

## Branches

| Branch  | Odoo.sh stage | Database |
|---------|---------------|----------|
| `main`  | Production    | the live database |
| `stage` | Staging       | neutralized duplicate of production |
| `dev`   | Development   | fresh empty database |

Work flows `dev` → `stage` → `main`. A branch's stage is set by drag-and-drop in the Odoo.sh
**Branches** tab; nothing in git controls it.

## Layout

Custom addons live directly at the repository root — one directory per module, each with its own
`__manifest__.py`. Nothing is implemented yet.

## Analysis documents

The technical investigation, implementation plan and proposed PRD §24 live outside this repo, in
`~/projects/seven-stars-investigation/`.
