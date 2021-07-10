This directory defines the https://www.klipper3d.org/ website.
The site is hosted using "github pages" (which uses Jekyll to
automatically convert the markdown files in the docs/ directory
to html). The "Just The Docs" Jekyll template is used to provide
a search functionality and a navigation tree.

## Site generation process

The site is generated and published to GitHub Pages by the
workflow `.github/workflows/klipper3d-deploy.yaml`. This
workflow first call the script `./pages_insert_metadata.py`
to insert the Jekyll metadata required to define the navigation
structure and then generate the html files that are pushed to the
`gh-pages` branch. This process is required to be able to keep the
orginal documentation markdown files free of Jekyll metadata for
viewing them on GitHub.

## Files impacting the site generation

- `./_config.yml` the Jekyll configuration file
- `./pages_metadata.ini` define the structure of the navigation tree
- `./*.md` the markdown files in this folder are used to define
  navigation tree levels not present in the original docs files.
- `./_includes/footer_custom.html` contains the customizations done
  to the JustTheDocs template (pages TOC and search term highlights)
- `./_sass/` this folder contains files overriding some parts of
  the template CSS


## How to add a new page to the navigation tree

The structure of the navigation is defined by the Jekyll metadata
that are in the file `pages_metadata.ini` and the markdown files
located in this folder. Follow the
[Just The Docs documentation](https://pmarsceill.github.io/just-the-docs/docs/navigation-structure/)
to see which metadata are required.

If the new page is only visible on klipper3d.org and is used to
add a level in the navigation tree, then create a new markdown file
with the metadata in the current folder. Otherwise, if it's a new
documentation page (created in the `docs/` folder), put the metadata
in the `pages_metadata.ini` file with the name of the `.md` file as
the section name.
