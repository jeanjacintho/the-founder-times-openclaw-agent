-- The Founder Times calendar desk. Copy this file VERBATIM into
-- plow_run_applescript (app: "Calendar"). Do not rewrite it.
--
-- Measured live 2026-09-18 on the owner's Mac:
--   1. Querying Calendar.app while it is closed returns
--      "Application isn't running" (-600) and the desk wrote an empty day.
--      `launch` then `delay 2` starts it.
--   2. Asking Calendar for "the time string of the first event of the
--      first calendar in one whose-clause" returns -1700 (Can't make
--      that into a type specifier). Walk each calendar, then each event
--      in a `whose` range, then read properties of THAT event.
--   3. A locale English date literal is fragile. Build the window from
--      `current date` with time set to 0.
--   4. No `try`: a swallowed calendar error printed EMPTY, which reads as a
--      free day. An error fails the call so the desk says it could not read.

tell application "Calendar" to launch
delay 2

set NL to linefeed
set out to ""

tell application "Calendar"
	set dayStart to current date
	set time of dayStart to 0
	set dayEnd to dayStart + (1 * days) - 1
	set weekEnd to dayStart + (8 * days) - 1
	repeat with cal in calendars
		set evList to (every event of cal whose end date > dayStart and start date ≤ weekEnd)
		repeat with ev in evList
			set s to start date of ev
			set e to end date of ev
			-- Today's rows carry no date, so clamp to today like events.json.
			if s < dayStart then set s to dayStart
			if s ≤ dayEnd and e > dayEnd then set e to dayEnd
			set t to summary of ev as text
			set isAll to allday event of ev
			set sh to hours of s as integer
			set sm to minutes of s as integer
			set eh to hours of e as integer
			set em to minutes of e as integer
			set startStamp to text -2 thru -1 of ("0" & sh) & ":" & text -2 thru -1 of ("0" & sm)
			set endStamp to text -2 thru -1 of ("0" & eh) & ":" & text -2 thru -1 of ("0" & em)
			set allFlag to "0"
			if isAll then
				set startStamp to "-"
				set endStamp to "-"
				set allFlag to "1"
			end if
			if s ≤ dayEnd then
				set kind to "TODAY"
				set dayStamp to "-"
			else
				set kind to "LATER"
				set y to year of s as integer
				set mo to month of s as integer
				set da to day of s as integer
				set dayStamp to (y as text) & "-" & text -2 thru -1 of ("0" & mo) & "-" & text -2 thru -1 of ("0" & da)
			end if
			set out to out & kind & tab & dayStamp & tab & startStamp & tab & endStamp & tab & allFlag & tab & t & NL
		end repeat
	end repeat
end tell

if out is "" then
	return "EMPTY"
end if
return out
