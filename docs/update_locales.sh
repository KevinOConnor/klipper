#!/bin/bash
#Automatically generate a set of po and md files for Localization
#in the ./locales/[language]/ folder
#requirement: pip install mdpo


for file in *.md; do
  echo "Converting $file to ${file//.md/.pot}"
  md2po $file --md-encoding utf-8 --po-encoding utf-8 \
  -e utf-8 -w 71 -q -s --po-filepath locales/en/${file//.md/.pot}
done

for dir in ./locales/*/; do
  dir=${dir%*/}
  dir=${dir##*/}
  if [ $dir != "en" ]; then
    echo "Updating ${dir##*/}"
    for file in *.md; do

    echo "Converting $file to ${file//.md/.pot}"
    md2po $file --md-encoding utf-8 --po-encoding utf-8 \
    -e utf-8 -w 71 -s --po-filepath locales/$dir/LC_MESSAGES/${file//.md/.po}

    echo "Converting ${file//.md/.po} to $file"
    po2md $file --md-encoding utf-8 --po-encoding utf-8 \
    --pofiles locales/$dir/LC_MESSAGES/${file//.md/.po} -q -s locales/$dir/$file
    done
  fi
done
