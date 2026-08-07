#!/bin/sh
# REL-029: wrapper entrypoint working around a real, confirmed upstream Grafana bug
# (grafana/grafana#69950) -- Grafana's own $__env{} provisioning-time substitution re-infers a
# scalar's JSON type from the substituted env var's text, so a purely-numeric Telegram chat_id
# gets coerced back into a JSON number no matter how the YAML source quotes/tags it, and
# provisioning then crashes with "cannot unmarshal number into Go struct field Config.chatid of
# type string" (confirmed live in this environment, both plain-quoted and explicit `!!str`-tagged
# attempts still failed identically).
#
# Real fix: substitute the real chat_id ourselves, in plain shell, before Grafana's own file
# provisioner ever reads the file -- so by the time Grafana parses it, chatid is already a
# concrete, correctly-quoted YAML string with no $__env{} token left for Grafana's buggy internal
# substitution to mis-type. The provisioning directory is mounted read-only at
# /etc/grafana/provisioning-src (see docker-compose.yml); this script copies it to a writable
# /etc/grafana/provisioning, patches the one broken field, and then hands off to Grafana's own
# real startup script unmodified.
set -e

mkdir -p /etc/grafana/provisioning
cp -r /etc/grafana/provisioning-src/. /etc/grafana/provisioning/

if [ -n "$TELEGRAM_ALERT_CHAT_ID" ]; then
  sed -i "s/__TELEGRAM_ALERT_CHAT_ID_PLACEHOLDER__/$TELEGRAM_ALERT_CHAT_ID/g" \
    /etc/grafana/provisioning/alerting/contact-points.yaml
fi

exec /run.sh "$@"
