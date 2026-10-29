# KPI Definitions — Draft

No KPI should be exposed until its operational definition is agreed and tested.

| KPI | Draft definition | Decisions needed |
|---|---|---|
| Offered | Contacts offered to a queue in the selected interval. | Which offered event timestamp defines interval membership? |
| Handled | Contacts answered/handled by an agent. | Transfer and multi-agent contact rules. |
| SLA | Percentage of eligible offered contacts answered within the configured threshold. | Per-channel threshold, short-abandon exclusion, and denominator. |
| ASA | Total answer wait time divided by answered contacts in the selected grain. | Treatment of callbacks, transfers, and missing waits. |
| AHT | (Talk time + hold time + after-contact work) / handled contacts, when all components exist. | Channel-specific variants and incomplete events. |
| Abandon rate | Eligible abandoned contacts divided by eligible offered contacts. | Short abandon exclusion and callback treatment. |
| Required staffing | Erlang C estimate based on arrival rate, AHT, interval duration, target answer-time threshold and target service level. | Occupancy ceiling, shrinkage, skills, and service-level assumptions. |

All reports must show the date/time window, time zone, service language filter (if any), channel/queue filters, metric definition/version, and any data-quality warning.
