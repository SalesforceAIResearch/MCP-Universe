# Web Data Extraction Task

Use Playwright MCP tools to extract all data from the specified website and present it in CSV format.

## Requirements:

1. Navigate to https://eval-web.mcpmark.ai/extraction
2. Wait for the page to fully load
3. Extract all data content from the page, including:
   - Title
   - Rating
   - Likes
   - Views
   - Replies
4. Organize the extracted data into CSV format
5. Ensure data completeness and accuracy
6. Output ONLY the complete CSV formatted data (no additional text or explanations)

## CSV Data Example:

```csv
Title, Rating, Likes, Views, Replies
SEO Optimization, "4.6", 756, 10123, 72
Vue 3 Composition API, "4.5", 743, 9876, 67
Advanced TypeScript Types Guide, "4.9", 924, 15432, 102
Node.js Performance Optimization, "4.2", 567, 8765, 45
Frontend Engineering Best Practices, "4.7", 812, 11234, 78
```

## Notes:

- Ensure extraction of all visible data rows
- Maintain data format consistency
- All numeric data (Rating, Likes, Views, Replies) should NOT have quotes, only text data containing commas should be wrapped in quotes
- Wait for the page to fully load before starting data extraction
- Verify the quantity and format of extracted data are correct
- **IMPORTANT: Final output must contain ONLY CSV data - no explanatory text, descriptions, or other content**
