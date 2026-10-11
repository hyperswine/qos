#!/bin/sh
# Shared lifecycle mechanics. Linux uses the kernel's process start token;
# the ps fallback lets the same lifecycle tests run on macOS.
set -f

qosp_config() {
	RUN_DIR=${QOSP_RUN_DIR:-/var/run/qosp}
	LOCK=$RUN_DIR/owner
	STATE_FILE=$RUN_DIR/state
	READY_FILE=${QOSP_READY_FILE:-$RUN_DIR/ready}
	SESSION=${QOSP_SESSION:-/usr/bin/qosp-session}
	SUPERVISOR=${QOSP_SUPERVISOR:-/usr/bin/qosp-supervise}
	GUARD=${QOSP_SERVICE_GUARD:-/usr/bin/qosp-service-guard}
	DETACH=${QOSP_SETSID:-setsid}
	READY_SECS=${QOSP_READY_TIMEOUT_SEC:-20}
	STOP_SECS=${QOSP_STOP_TIMEOUT_SEC:-15}
	KILL_SECS=${QOSP_KILL_TIMEOUT_SEC:-2}
	RESTART_MAX=${QOSP_RESTART_MAX:-3}
	BACKOFF_SECS=${QOSP_RESTART_DELAY_SEC:-1}
	BACKOFF_MAX=${QOSP_RESTART_DELAY_MAX_SEC:-30}
	case $RUN_DIR in /*) ;; *) echo "qosp: QOSP_RUN_DIR must be absolute" >&2; return 1 ;; esac
	for n in "$READY_SECS" "$STOP_SECS" "$KILL_SECS" "$RESTART_MAX" "$BACKOFF_SECS" "$BACKOFF_MAX"; do
		case $n in ''|*[!0-9]*|0?*) echo "qosp: lifecycle settings must be decimal integer seconds/counts without leading zeros" >&2; return 1 ;; esac
		[ "$n" -le 3600 ] || { echo "qosp: lifecycle setting exceeds 3600" >&2; return 1; }
	done
	[ "$READY_SECS" -gt 0 ] && [ "$STOP_SECS" -gt 0 ] && [ "$KILL_SECS" -gt 0 ] &&
		[ "$RESTART_MAX" -le 100 ] && [ "$BACKOFF_SECS" -le "$BACKOFF_MAX" ] || {
		echo "qosp: invalid lifecycle timeout/restart limits" >&2; return 1;
	}
}

qosp_identity() {
	case $1 in ''|*[!0-9]*) return 1 ;; esac
	[ "$1" -gt 1 ] || return 1
	if [ -r "/proc/$1/stat" ]; then
		stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
		# Field 2 is parenthesized and may itself contain spaces/parentheses.
		stat=${stat##*) }
		set -- $stat
		[ "$#" -ge 20 ] || return 1
		[ "$1" != Z ] || return 1
		shift 19
		printf 'linux:%s\n' "$1"
	else
		stat=$(ps -p "$1" -o stat= 2>/dev/null) || return 1
		case $stat in ''|*Z*) return 1 ;; esac
		stat=$(ps -p "$1" -o lstart= 2>/dev/null) || return 1
		[ -n "$stat" ] || return 1
		printf 'ps:%s\n' "$stat"
	fi
}

qosp_matches() {
	[ -n "$2" ] || return 1
	actual=$(qosp_identity "$1") || return 1
	[ "$actual" = "$2" ]
}

qosp_recorded() {
	[ -r "$LOCK/$1.pid" ] && [ -r "$LOCK/$1.identity" ] || return 1
	recorded_pid=$(cat "$LOCK/$1.pid")
	recorded_identity=$(cat "$LOCK/$1.identity")
	qosp_matches "$recorded_pid" "$recorded_identity"
}

qosp_write_record() { printf '%s\n' "$2" > "$1"; }

# Before fork the owner records a pending launch. Missing/partial identity
# files after that point cannot prove that no writer remains. Complete start
# identities can still establish that an old child has died or its PID reused.
qosp_child_uncertain() {
	[ ! -e "$LOCK/child.pending" ] || return 0
	if [ -r "$LOCK/child.pid" ] && [ -s "$LOCK/child.identity" ]; then
		candidate=$(cat "$LOCK/child.pid")
		case $candidate in ''|*[!0-9]*) ;; *) [ "$candidate" -le 1 ] || return 1 ;; esac
	fi
	[ -e "$LOCK/child.pending" ] || [ -e "$LOCK/child.pid" ] || [ -e "$LOCK/child.identity" ]
}

qosp_state() {
	printf '%s\n' "$*" > "$STATE_FILE.tmp.$$" && mv -f "$STATE_FILE.tmp.$$" "$STATE_FILE"
}

qosp_unlock() {
	target=$LOCK
	if [ -L "$LOCK" ]; then
		target=$(readlink "$LOCK") || return 1
		suffix=${target#"$RUN_DIR/instance."}
		case $suffix in ''|*[!0-9]*) echo "qosp: invalid ownership link" >&2; return 1 ;; esac
		[ "$target" = "$RUN_DIR/instance.$suffix" ] || return 1
	fi
	rm -f "$target/supervisor.pid" "$target/supervisor.identity" "$target/child.pid" "$target/child.identity" "$target/child.pending" "$target/stop"
	if [ -d "$target" ]; then rmdir "$target" 2>/dev/null || [ ! -d "$target" ] || return 1; fi
	[ ! -L "$LOCK" ] || rm -f "$LOCK"
}

qosp_signal_child() {
	qosp_matches "$child" "$child_identity" || return 0
	# Each child is a session leader. Terminate any helpers it started too.
	kill -"$1" -- "-$child" 2>/dev/null || kill -"$1" "$child" 2>/dev/null
}
