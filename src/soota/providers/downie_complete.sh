# Soota Downie completion hook v1
# Paste into Downie Settings > Postprocessing > Custom > Edit Custom Script.
# Other downloads are left unchanged. Downie invokes this only after downloading.
file=$1
dir=$(dirname "$file")
case "${dir##*/}" in
    soota-downie-*) ;;
    *) exit 0 ;;
esac
[ -f "$dir/request.json" ] || exit 0
[ -f "$file" ] || exit 1
case "$file" in
    *.mp4|*.mkv|*.webm|*.mov|*.m4a|*.mp3|*.aac|*.wav|*.ogg|*.flac|*.opus) ;;
    *) exit 0 ;;
esac
printf '%s' "$file" > "$dir/complete.path.tmp" || exit 1
mv "$dir/complete.path.tmp" "$dir/complete.path"
