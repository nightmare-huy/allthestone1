# allthestone1 - mod jar store

Do not edit by hand. This branch only exists so the jars can be fetched over the
git protocol on networks where the mod CDNs are filtered:

    git fetch origin mods-store
    git archive FETCH_HEAD mods | tar -x

The pack itself lives on the default branch.
