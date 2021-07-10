This document provides contact information for Klipper.

1. [Community Forum](#community-forum)
2. [Discord Chat](#discord-chat)
3. [I have a question about Klipper](#i-have-a-question-about-klipper)
4. [I have a feature request](#i-have-a-feature-request)
5. [Help! It doesn't work!](#help-it-doesnt-work)
6. [I have diagnosed a defect in the Klipper software](#i-have-diagnosed-a-defect-
in-the-klipper-software)
7. [I am making changes that I'd like to include in Klipper](#i-am-making-changes-
that-id-like-to-include-in-klipper)

# Community Forum

There is a [Klipper Community Discourse server](https://community.klipper3d.org)
for discussions on Klipper.

# Discord Chat

There is a Discord server dedicated to Klipper at:
<https://discord.klipper3d.org>.

This server is run by a community of Klipper enthusiasts dedicated to
discussions on Klipper. It allows users to chat with other users in real-time.

# I have a question about Klipper

Many questions we receive are already answered in the [Klipper
documentation](Overview.md). Please be sure to to read the documentation and
follow the directions provided there.

It is also possible to search for similar questions in the [Klipper Community
Forum](#community-forum).

If you are interested in sharing your knowledge and experience with other
Klipper users then you can join the [Klipper Community Forum](#community-forum)
or [Klipper Discord Chat](#discord-chat). Both are communities where Klipper
users can discuss Klipper with other users.

Many questions we receive are general 3d-printing questions that are not
specific to Klipper. If you have a general question or are experiencing general
printing problems, then you will likely get a better response by asking in a
general 3d-printing forum or a forum dedicated to your printer hardware.

Do not open a Klipper github issue to ask a question.

# I have a feature request

All new features require someone interested and able to implement that feature.
If you are interested in helping to implement or test a new feature, you can
search for ongoing developments in the [Klipper Community Forum](#community-
forum). There is also [Klipper Discord Chat](#discord-chat) for discussions
between collaborators.

Do not open a Klipper github issue to request a feature.

# Help! It doesn't work!

Unfortunately, we receive many more requests for help than we could possibly
answer. Most problem reports we see are eventually tracked down to:

1. Subtle errors in the hardware, or
2. Not following all the steps described in the Klipper documentation.

If you are experiencing problems we recommend you carefully read the [Klipper
documentation](Overview.md) and double check that all steps were followed.

If you are experiencing a printing problem, then we recommend carefully
inspecting the printer hardware (all joints, wires, screws, etc.) and verify
nothing is abnormal. We find most printing problems are not related to the
Klipper software. If you do find a problem with the printer hardware then you
will likely get a better response by searching in a general 3d-printing forum or
in a forum dedicated to your printer hardware.

It is also possible to search for similar issues in the [Klipper Community
Forum](#community-forum).

If you are interested in sharing your knowledge and experience with other
Klipper users then you can join the [Klipper Community Forum](#community-forum)
or [Klipper Discord Chat](#discord-chat). Both are communities where Klipper
users can discuss Klipper with other users.

Do not open a Klipper github issue to request help.

# I have diagnosed a defect in the Klipper software

Klipper is an open-source project and we appreciate when collaborators diagnose
errors in the software.

There is important information that will be needed in order to fix a bug. Please
follow these steps:

1. Be sure the bug is in the Klipper software. If you are thinking "there is a
problem, I can't figure out why, and therefore it is a Klipper bug", then **do
not** open a github issue. In that case, someone interested and able will need
to first research and diagnose the root cause of the problem. If you would like
to share the results of your research or check if other users are experiencing
similar issues then you can search the [Klipper Community Forum](#community-
forum).

2. Make sure you are running unmodified code from
<https://github.com/KevinOConnor/klipper>. If the code has been modified or is
obtained from another source, then you will need to reproduce the problem on the
unmodified code from <https://github.com/KevinOConnor/klipper> prior to
reporting an issue.

3. If possible, run an `M112` command in the OctoPrint terminal window immediately
after the undesirable event occurs. This causes Klipper to go into a "shutdown
state" and it will cause additional debugging information to be written to the
log file.

4. Obtain the Klipper log file from the event. The log file has been engineered to
answer common questions the Klipper developers have about the software and its
environment (software version, hardware type, configuration, event timing, and
hundreds of other questions).

   1. The Klipper log file is located in `/tmp/klippy.log` on the Klipper "host"
computer (the Raspberry Pi).
   2. An "scp" or "sftp" utility is needed to copy this log file to your desktop
computer. The "scp" utility comes standard with Linux and MacOS desktops.
There are freely available scp utilities for other desktops (eg, WinSCP). If
using a graphical scp utility that can not directly copy `/tmp/klippy.log` then
repeatedly click on `..` or `parent folder` until you get to the root
directory, click on the `tmp` folder, and then select the `klippy.log` file.
   3. Copy the log file to your desktop so that it can be attached to an issue
report.
   4. Do not modify the log file in any way; do not provide a snippet of the log.
Only the full unmodified log file provides the necessary information.
   5. If the log file is very large (eg, greater than 2MB) then one may need to
compress the log with zip or gzip.

5. Open a new github issue at <https://github.com/KevinOConnor/klipper/issues> and
provide a clear description of the problem. The Klipper developers need to
understand what steps were taken, what the desired outcome was, and what outcome
actually occurred. The Klipper log file **must be attached** to that ticket:
![attach-issue](img/attach-issue.png)


# I am making changes that I'd like to include in Klipper

Klipper is open-source software and we appreciate new contributions.

New contributions (for both code and documentation) are submitted via Github
Pull Requests. See the [CONTRIBUTING document](CONTRIBUTING.md) for important
information.

There are several [documents for developers](Overview.md#developer-
documentation). If you have questions on the code then you can also ask in the
[Klipper Community Forum](#community-forum) or on the [Klipper Community
Discord](#discord-chat). If you would like to provide an update on your current
progress then you can open a Github issue with the location of your code, an
overview of the changes, and a description of its current status.
