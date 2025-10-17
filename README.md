# SQL Server Maintenance Tool - Web Interface

A modern web-based interface for executing SQL Server database maintenance operations across multiple servers. This tool provides a user-friendly frontend for the SQL maintenance script that performs database compression, optimization, and space reduction.

## Features

- **Excel File Upload**: Upload server lists from Excel files (.xlsx, .xls)
- **Real-time Progress Tracking**: Monitor server processing with live updates
- **Terminal-inspired Interface**: Clean, modern UI with terminal aesthetics
- **Comprehensive Results**: Detailed reports with size reductions and statistics
- **Configuration Management**: Customizable database connection settings
- **Export Functionality**: Export logs and results to files

## Prerequisites

- Python 3.8 or higher
- SQL Server with ODBC Driver 17 for SQL Server
- Network access to target SQL Server instances
- Required Python packages (see requirements.txt)

## Installation

1. **Clone or download the project files**
   ```bash
   # Ensure you have all files in your project directory:
   # - index.html
   # - styles.css
   # - script.js
   # - web_server.py
   # - ex1.py (original script)
   # - requirements.txt
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Verify ODBC Driver installation**
   - Ensure "ODBC Driver 17 for SQL Server" is installed on your system
   - You can download it from Microsoft's website if not present

## Usage

### Starting the Web Server

1. **Run the web server**
   ```bash
   python web_server.py
   ```

2. **Open your web browser**
   - Navigate to: `http://localhost:5000`
   - The interface will load with the upload form

### Using the Interface

1. **Upload Server List**
   - Click "Choose Excel File" and select your Excel file
   - The file should contain server names in the first column
   - Example Excel format:
     ```
     | Server Name    |
     |----------------|
     | APHSC0095-PC   |
     | APHSC0096-PC   |
     | APHSC0097-PC   |
     ```

2. **Configuration (Backend)**
   - All configuration is handled on the backend with sensible defaults:
     - Database name: POSDBIR
     - Username: apposcr
     - Password: 2#06A9a
     - Query timeout: 900 seconds
     - Server timeout: 1800 seconds
   - Configuration can be modified via API endpoints if needed

3. **Start Processing**
   - Click "Start Processing" to begin maintenance operations
   - Monitor real-time progress in the progress section
   - View live logs in the console output

4. **Review Results**
   - Once complete, view the results summary
   - Check individual server results in the detailed table
   - Export logs and results as needed

## Excel File Format

The Excel file should have the following structure:

- **First column**: Server names (required)
- **Size data columns**: Optional, will be extracted if present
- **File formats**: .xlsx or .xls

### Basic Format (Server names only)
```
| Server Name    | Description     | Environment |
|----------------|-----------------|-------------|
| APHSC0095-PC   | Production DB   | PROD        |
| APHSC0096-PC   | Test DB         | TEST        |
```

### Extended Format (With size data)
```
| Server Name    | Initial Size (GB) | Final Size (GB) | Space Saved (GB) | Reduction % |
|----------------|-------------------|-----------------|------------------|-------------|
| APHSC0095-PC   | 150.25           | 120.50          | 29.75            | 19.8        |
| APHSC0096-PC   | 89.30            | 71.44           | 17.86            | 20.0        |
```

### Supported Column Names
The system automatically detects size data using these column name variations:

- **Initial Size**: `Initial Size (GB)`, `Initial Size`, `InitialSize`, `Initial_Size`
- **Final Size**: `Final Size (GB)`, `Final Size`, `FinalSize`, `Final_Size`
- **Space Saved**: `Space Saved (GB)`, `Space Saved`, `SpaceSaved`, `Space_Saved`
- **Reduction %**: `Reduction %`, `Reduction`, `ReductionPercent`, `Reduction_Percent`

### Data Handling
- If size data is present in Excel, it will be used in results display
- If size data is missing, the system will show processing results
- Mixed scenarios are supported (some servers with data, others without)

## API Endpoints

The web server provides the following REST API endpoints:

- `POST /api/upload` - Upload and parse Excel file
- `POST /api/process` - Start server processing
- `GET /api/status` - Get current processing status
- `GET /api/results` - Get final results
- `POST /api/stop` - Stop current processing
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration

## Maintenance Operations

The tool performs the following operations on each server:

1. **Database Size Analysis**
   - Initial size measurement
   - Compression status check

2. **Index Optimization**
   - ALTER INDEX statements with PAGE compression
   - Parallel execution for performance

3. **Table Optimization**
   - ALTER TABLE statements with PAGE compression
   - Heap table rebuilding

4. **Database Shrinking**
   - Multiple POSDBSHRINK executions
   - DBCC SHRINKDATABASE operations

5. **Statistics Update**
   - UPDATE STATISTICS with FULLSCAN
   - Performance optimization

6. **Final Analysis**
   - Final size measurement
   - Reduction calculation

## Configuration

### Database Connection
- **Server**: Extracted from Excel file
- **Database**: POSDBIR (configurable via API)
- **Authentication**: SQL Server authentication
- **Driver**: ODBC Driver 17 for SQL Server

### Default Settings
- **Database**: POSDBIR
- **Username**: apposcr
- **Password**: 2#06A9a
- **Query Timeout**: 900 seconds
- **Server Timeout**: 1800 seconds

### Configuration Management
- Configuration is managed on the backend
- Default values are used unless modified via API
- Configuration can be updated using `/api/config` endpoints
- Changes persist during the server session

## Troubleshooting

### Common Issues

1. **"ODBC Driver not found"**
   - Install ODBC Driver 17 for SQL Server
   - Verify driver installation in ODBC Data Sources

2. **"Connection failed"**
   - Check network connectivity to SQL servers
   - Verify credentials and database name
   - Ensure SQL Server allows remote connections

3. **"File upload failed"**
   - Check file format (.xlsx or .xls)
   - Verify file size (max 16MB)
   - Ensure first column contains server names

4. **"Processing timeout"**
   - Increase server timeout settings
   - Check server performance and load
   - Verify database size and complexity

### Log Analysis

- All operations are logged with timestamps
- Logs include success/failure status
- Error messages provide detailed information
- Export logs for troubleshooting

## Security Considerations

- **Credentials**: Store securely, consider environment variables
- **Network**: Ensure secure network connections
- **Access**: Limit server access to authorized personnel
- **Logs**: Review logs for sensitive information

## Performance Optimization

- **Parallel Processing**: Servers processed concurrently
- **Batch Operations**: Statements executed in batches
- **Connection Pooling**: Efficient database connections
- **Progress Tracking**: Real-time status updates

## File Structure

```
SQL Query/
├── index.html          # Main web interface
├── styles.css          # Styling and layout
├── script.js           # Frontend JavaScript
├── web_server.py       # Flask web server
├── ex1.py             # Original maintenance script
├── requirements.txt    # Python dependencies
└── README.md          # This documentation
```

## Support

For issues or questions:
1. Check the console logs for error messages
2. Verify configuration settings
3. Test database connectivity manually
4. Review server permissions and access

## License

This tool is provided as-is for internal use. Ensure compliance with your organization's policies and SQL Server licensing requirements.
