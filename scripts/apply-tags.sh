#!/bin/sh
# Tag every commit whose subject starts with "[PRD_xx_yy]" with that name, then print the push command.
# (The cloud session that made these commits can't push tags, so run this once on your PC after `git pull`.)
cd "$(git rev-parse --show-toplevel)" || exit 1
git log --reverse --format='%H %s' | while read -r sha subject; do
  tag=$(printf '%s' "$subject" | sed -n 's/^\[\(PRD_[0-9_]*\)\].*/\1/p')
  [ -z "$tag" ] && continue
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "skip   $tag (exists)"
  else
    git tag -a "$tag" "$sha" -m "$subject" && echo "tagged $tag -> $(echo "$sha" | cut -c1-7)"
  fi
done
echo "Now run: git push origin --tags"
