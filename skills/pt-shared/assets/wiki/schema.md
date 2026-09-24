---
type: Schema
root: projects/theplowtimes
required: [type, title, description, category, tags, sources, created, updated]
fields:
  type: {enum: [Project, Synthesis, Advisor, Edition]}
  paper: {type: link}
  date: {type: date}
tables:
  - into: paper
    section: "## Editions"
    match: {type: Edition}
    sort_by: date
    columns: [title, description]
  - into: paper
    section: "## Your advisors"
    match: {type: Advisor}
    sort_by: title
    columns: [title, description]
title: projects/theplowtimes schema
category: meta
tags: [schema]
sources: []
created: {today}
updated: {today}
---
# projects/theplowtimes/

The Founder Times writes here. Every page links back to the paper's page with
`paper:`, so `wiki index` lists editions and advisors there.
