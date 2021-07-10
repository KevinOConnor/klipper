#!/bin/bash
#Automatically generate a set of po and md files for Localization
#in the ./locales/[language]/ folder
#requirement: pip install mdpo

width=71

for file in docs/*.md; do
  mdfile=${file/docs\//}
  potfile=${mdfile//.md/.pot}
  echo "Converting $mdfile to $potfile"
  echo "md2po docs/$mdfile --md-encoding utf-8 --po-encoding utf-8 \
   -e utf-8 -w $width -q -s --po-filepath docs/locales/en/$potfile"
  md2po docs/$mdfile --md-encoding utf-8 --po-encoding utf-8 -e utf-8 \
  -w $width -q -s --po-filepath docs/locales/en/$potfile
done

for dir in docs/locales/*/; do
  dir=${dir%*/}
  dir=${dir##*/}
  if [ $dir != "en" ]; then
    echo "Updating $dir"
    for file in docs/*.md; do
      mdfile=${file/docs\//}
      pofile=${mdfile//.md/.po}
      echo "Converting $mdfile to $pofile"
      echo "md2po docs/$mdfile --md-encoding utf-8 --po-encoding utf-8 \
      -e utf-8 -w $width -q -s --po-filepath docs/locales/$dir/LC_MESSAGES/$pofile"
      md2po docs/$mdfile --md-encoding utf-8 --po-encoding utf-8 \
      -e utf-8 -w $width -q -s --po-filepath docs/locales/$dir/LC_MESSAGES/$pofile
      echo "Converting $pofile to $mdfile"
      echo "po2md docs/$mdfile --md-encoding utf-8 --po-encoding utf-8 \
      -p docs/locales/$dir/LC_MESSAGES/$pofile -q -s docs/locales/$dir/$mdfile"
      po2md docs/$mdfile --md-encoding utf-8 --po-encoding utf-8 \
      -p docs/locales/$dir/LC_MESSAGES/$pofile -q -s docs/locales/$dir/$mdfile
    done
  fi
done
