# Closing the console froze the whole machine — how, and what we owed the driver

*2026-08-08. Forensics for a hard desktop freeze that followed quitting the
daemon by closing its terminal, and the reason the fix is about **teardown
order** rather than anything in the decode path. Companion to the #10 freeze
lineage (`test_daemon_finish.py`), which until now was about our GUI thread
blocking — this one was about the GPU.*

## What was reported

> I closed TuParles (brutally, closing the console) and it crashed my PC.

Symptoms, in the user's order: fans went to full power, the screen froze, audio
kept playing in the background, keyboard and mouse did nothing. After about a
minute they held the power button.

## What the logs said

Nothing, at first — and that absence is the most useful fact in this note.

The journal for that boot ends mid-sentence:

```
01:40:09  last sysstat sample: 37% memory, 0 swap-in, load 1.7, 0 blocked tasks
01:43:48  gsd-power: Failed to acquire idle monitor proxy: Timeout was reached  (x2)
          <nothing, ever again>
```

Read backwards, those two lines date the freeze. `gsd-power` had asked
gnome-shell's IdleMonitor a question over D-Bus and waited out the 25-second
default timeout — so **gnome-shell stopped answering at ~01:43:23**. journald
never persisted another line: not the 01:45 cron, not the 01:50 sysstat sample,
not the minute the user spent waiting, not the power-button kill.

Everything the system *could* still tell us said the box was healthy right up to
the edge: 92% idle CPU for the preceding hour, no swap thrash, no OOM kill, no
`Xid`, no crash dump, zero blocked tasks at the last sample. This was not a
resource death. Something wedged, all at once.

## The mechanism, caught red-handed

The freeze itself left no kernel trace — journald was already gone. But the same
machine reproduced the failure hours later, in a boot that survived long enough
to log it:

```
INFO: task nvidia-smi:1639 blocked for more than 122 seconds.
  rwsem_down_write_slowpath → down_write
  os_acquire_rwlock_write [nvidia] → portSyncRwLockAcquireWrite [nvidia]
  rmapiLockAcquire [nvidia] → serverAllocResource [nvidia] → RmIoctl [nvidia]
INFO: task nvidia-smi:1639 <writer> blocked on an rw-semaphore
     likely owned by task kworker/15:0:110 <writer>
task:kworker/15:0    state:I     ← parked. Not working. Just never dropped it.
```

The same stack for `gpu-manager`, `llama-server` (×3), a `udev-worker`, a
kworker. Every process that touches the GPU, stuck in uninterruptible sleep on
the **NVIDIA RM API global write lock**, held by a worker that will never
release it. Driver-side deadlock (NVIDIA open kernel module 580.159.03).

That single lock explains every symptom, including the strange ones:

| Symptom | Cause |
| --- | --- |
| Screen frozen, input dead | gnome-shell renders on `/dev/dri/card2` (nvidia-drm) → it blocks in D state. Under Wayland the compositor *is* the input path, so input dies with it |
| Audio kept playing | PipeWire is not a GPU client. Nothing in its path takes that lock |
| Fans at full | GPU pinned at clocks with nothing able to run a power transition — `gpu-manager` is itself blocked reading `/proc/driver/nvidia/.../power` |
| Empty journal | the writers starve behind the same wall |

The whole box was not dead. Everything that never speaks to the GPU was fine.
That is why it *looked* like a total crash from the keyboard, and why a hard
power-off felt like the only option. (For next time: ssh from a phone, or SysRq,
would both still have worked — and would have distinguished this from a real
kernel death.)

## Why closing the console is the trigger

Closing a terminal emulator sends **SIGHUP** to the foreground process group.
Our daemon handled `SIGINT` and nothing else, and Python's default action for
SIGHUP is to terminate immediately — no `aboutToQuit`, no `atexit`, no chance to
release anything. The process simply stopped existing with a live CUDA context.

Someone still has to tear that context down, and with the process gone it is the
driver, from the kernel side, holding the RM API write lock while it does. That
reclaim is precisely the operation the trace above shows deadlocking.

Two things made this box a good place for it to happen. `engine.py` had **no
release path at all** — the model lived until the process died, so *every* exit
was a driver-side reclaim, orderly or not. And a 6 GB card was shared with
another persistent CUDA client (`ollama serve`, one of the hung tasks in the
trace), so a reclaim rarely had the driver to itself.

## What we changed, and what we deliberately did not

The deadlock is the driver's bug and we cannot fix it. What we can stop doing is
handing it the worst possible teardown.

1. **Quit cleanly whatever asks.** `SIGHUP` and `SIGTERM` join `SIGINT` on the
   path to `app.quit()`. A closed console, a `pkill`, a logout: all now run the
   same shutdown as Ctrl-C.
2. **Release the context ourselves, while the GPU is quiet.** `GpuEngine.close()`
   drops the model and collects the cycle; `ResilientEngine.close()` releases
   every rung it built. `aboutToQuit` calls it. The reclaim still happens — it
   just happens in-process, on our schedule, with no other GPU work in flight.
3. **Never free a model under a live decode.** `Controller.shutdown()` bars new
   partials, sends the queue's shutdown sentinel, and *joins the decode worker*.
   It returns a boolean, and `run()` respects it: no quiet worker, no release.
   A possible wedge beats a certain segfault, and a long take still gets its
   five seconds to land rather than being cut off at the door.
4. **Close before rebuilding.** `_rebuild_gpu()` (the suspend/resume recovery)
   now releases the dead context first. Each recovery used to leave another
   orphan for the driver to collect later — all at once, at process death,
   which is the stacked version of exactly this bug.

What we did **not** do: add a GPU health check, a watchdog that kills the
daemon, or any retry around the lock. Once that semaphore is held by a parked
worker, nothing in userspace can help; a process that tries only adds another
task to the D-state pile. The honest scope here is our own teardown.

## The instrument that was blind

The persistent heartbeat exists precisely to date a freeze like this. Its
comment promised *"into journald which survives reboots — after the next freeze,
the last `hb:` line dates when we went silent"*. It was a `print()`.

Launched from the desktop entry that is true (GNOME pipes our stdout to
journald). Launched from a **terminal** — the way anyone runs it while working
on it, the way it was running that night — stdout is the tty, and the tty died
with the window. The freeze that most wanted dating left no beat behind at all.

So `_journal()` now prints *and* writes to syslog (journald's `/dev/log`, via
the stdlib; no new dependency), and the heartbeat, the GUI-stall lines and the
shutdown path all go through it. `journalctl -t tuparles` finds them either way.

The lesson generalises past this bug: **a forensic log that only survives one
launch method is not a forensic log.** Ours claimed a durability it did not
have, and we believed the claim for two months.

## Postscript: the battery was a red herring

The first pass at this investigation concluded "the battery ran out" — the
laptop had been unplugged at 00:36 (dock disconnect), discharged at ~38 W, and
the pack is at 56% health (52.4 Wh of 93.5 Wh design), so it died with the gauge
still reading 24%. All of that is true and none of it ended the session: the
user's own account (fans, freeze, held the power button) is a hang, and the
gsd-power timeout confirms the compositor stopped answering before the power
went anywhere.

Worth keeping in view anyway, because it is a real trap on this hardware: a worn
pack that collapses at a reported 24% means GNOME's critical-battery hibernate
(which waits for ~3%) will never fire. Two independent problems, one evening.
The forensics only separated them because the *user* described symptoms the logs
could not — which is the other lesson here.
