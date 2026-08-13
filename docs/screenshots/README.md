# Screenshots

Images referenced from the project documentation.

| File name | What it shows | Status |
| --- | --- | --- |
| `dashboard.png` | The Analyse view end to end: the upload control, the score/status/row/column/issue metrics, the quality-dimensions bar chart, and the Recommendations tab | Captured |

## Still wanted

| File name | What to capture |
| --- | --- |
| `dashboard-validation.png` | The Validation tab showing the issues table |
| `dashboard-profile.png` | The Profile tab showing per-column statistics |
| `dashboard-charts.png` | The Charts tab with an interactive histogram, box plot, or correlation heatmap |
| `dashboard-compare-drift.png` | Compare mode showing schema and data drift |
| `report-html.png` | The rendered HTML report, including embedded charts |
| `report-pdf.png` | A page of the generated PDF report |

## How to capture

Run the dashboard against a sample dataset, or generate a report to photograph:

```bash
dqms dashboard
dqms report data/samples/customers.csv --output output/
```

Capture at a standard desktop width. Two rules, in order of importance:

1. **Never include real or sensitive data.** Use `data/samples/`, which is entirely synthetic -
   addresses on the reserved `example.com` domain and telephone numbers in the reserved `555-01XX`
   range.
2. **Keep the operator's machine out of the frame.** No taskbar, no browser address bar or bookmark
   strip, no title bar containing a local path or user name. If a browser cannot go full-screen,
   capture the page in sections and stitch them - `dashboard.png` was produced that way.

Save as PNG. Screenshots taken by some tools carry EXIF or vendor metadata; write the final file with
an image library (or strip it) so nothing about the capturing machine ships with the repository.
