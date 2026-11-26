const sessionDate = new Intl.DateTimeFormat("en-US", {month: "short", day: "numeric", timeZone: "UTC"});
const marketTime = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  timeZone: "America/New_York", timeZoneName: "short",
});
export const session = (day: string) => sessionDate.format(new Date(day + "T12:00:00Z"));
export const eastern = (iso: string) => marketTime.format(new Date(iso));
