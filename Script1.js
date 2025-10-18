// Global variables
let currentFile = null;
let servers = [];
let serverData = [];
let isProcessing = false;
let startTime = null;
let serverResults = {};
let processedServers = 0;
let totalServers = 0;
let processingStartTime = null; // in milliseconds
let processingEndTime = null; // in milliseconds

// DOM elements
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const startProcessBtn = document.getElementById('startProcess');
const uploadSection = document.getElementById('uploadSection');
const progressSection = document.getElementById('progressSection');
const resultsSection = document.getElementById('resultsSection');
const serverList = document.getElementById('serverList');
const consoleContent = document.getElementById('consoleContent');
const overallProgressBar = document.getElementById('overallProgressBar');
const progressFill = document.getElementById('progressFill');
const overallProgress = document.getElementById('overallProgress');
const elapsedTime = document.getElementById('elapsedTime');
const loadingOverlay = document.getElementById('loadingOverlay');


// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initializeEventListeners();
});

function initializeEventListeners() {
    // File input handling
    fileInput.addEventListener('change', handleFileSelect);
    startProcessBtn.addEventListener('click', startProcessing);
    
    // Control buttons
    document.getElementById('clearLog').addEventListener('click', clearConsole);
    
    // Results buttons
    document.getElementById('exportLogs').addEventListener('click', exportLogs);
    document.getElementById('exportResults').addEventListener('click', exportResults);
    document.getElementById('newProcess').addEventListener('click', resetToUpload);
    
}


function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    // Validate file type
    const validTypes = [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel'
    ];
    
    if (!validTypes.includes(file.type)) {
        alert('Please select a valid Excel file (.xlsx or .xls)');
        return;
    }
    
    currentFile = file;
    displayFileInfo(file);
    parseExcelFile(file);
}

function displayFileInfo(file) {
    const fileName = document.querySelector('.file-name');
    const fileSize = document.querySelector('.file-size');
    
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    
    fileInfo.classList.remove('hidden');
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

async function parseExcelFile(file) {
    try {
        logToConsole('Reading Excel file...', 'info');
        
        // Create FormData for file upload
        const formData = new FormData();
        formData.append('file', file);
        
        // Log the file being uploaded
        console.log('Uploading file:', file.name);
        
        // Upload file to backend
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            servers = data.servers;
            serverData = data.server_data || [];
            
            logToConsole(`Found ${servers.length} servers in the file`, 'success');
            logToConsole('Servers: ' + servers.join(', '), 'info');
            
            // Log size data information if available
            if (data.has_size_data) {
                logToConsole('Size data detected in Excel file', 'success');
                const serversWithData = serverData.filter(server => 
                    server.initial_size || server.final_size || server.space_saved || server.reduction_percent
                );
                logToConsole(`${serversWithData.length} servers have size data`, 'info');
            }
            
            // Update start button state
            startProcessBtn.disabled = false;
            startProcessBtn.innerHTML = '<i class="fas fa-play"></i> Start Processing';
        } else {
            throw new Error(data.error || 'Failed to parse Excel file');
        }
        
    } catch (error) {
        logToConsole('Error reading Excel file: ' + error.message, 'error');
        startProcessBtn.disabled = true;
    }
}

function startProcessing() {
    if (!currentFile || servers.length === 0) {
        alert('Please select a valid Excel file first');
        return;
    }
    
    isProcessing = true;
    startTime = new Date();
    totalServers = servers.length;
    processedServers = 0;
    serverResults = {};
    
    // Switch to progress view
    uploadSection.classList.add('hidden');
    progressSection.classList.remove('hidden');
    resultsSection.classList.add('hidden');
    
    // Initialize progress
    updateOverallProgress();
    createServerItems();
    
    // Start processing
    processServers();
}

function createServerItems() {
    serverList.innerHTML = '';
    
    servers.forEach((server, index) => {
        const serverItem = document.createElement('div');
        serverItem.className = 'server-item';
        serverItem.id = `server-${index}`;
        
        serverItem.innerHTML = `
            <div class="server-header">
                <span class="server-name">${server}</span>
                <span class="server-status status-processing">
                    <i class="fas fa-spinner fa-spin"></i>
                    Processing
                </span>
            </div>
            <div class="server-progress-bar">
                <div class="server-progress-fill" id="progress-${index}"></div>
            </div>
            <div class="server-details">
                <span>Status: <span id="status-${index}">Initializing...</span></span>
                <span>Size: <span id="size-${index}">-</span></span>
                <span>Time: <span id="time-${index}">00:00:00</span></span>
            </div>
        `;
        
        serverList.appendChild(serverItem);
    });
}

async function processServers() {
    // Start the timer
    const timerInterval = setInterval(updateTimer, 1000);
    
    try {
        console.log('Starting processing with servers:', servers);
        
        // Start backend processing
        const response = await fetch('/api/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                servers: servers,
                server_data: serverData
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            logToConsole('Backend processing started successfully', 'success');
            
            // Poll for status updates
            const statusInterval = setInterval(async () => {
                try {
                    const statusResponse = await fetch('/api/status');
                    if (statusResponse.ok) {
                        const statusData = await statusResponse.json() || {};
                        
                        // Ensure all required properties exist with defaults
                        const safeStatusData = {
                            is_processing: statusData.is_processing || false,
                            results: statusData.results || {},
                            servers: statusData.servers || [],
                            current_server: statusData.current_server || null,
                            logs: statusData.logs || [],
                            progress: statusData.progress || 0
                        };
                        
                        updateProgressFromBackend(safeStatusData);
                        
                        // Debug information
                        console.log('Status check:', {
                            is_processing: safeStatusData.is_processing,
                            processedServers: Object.keys(safeStatusData.results).length,
                            totalServers: safeStatusData.servers.length,
                            results: safeStatusData.results
                        });
                        
                        // Check if all servers have been processed (including failed ones)
                        const processedServers = Object.keys(statusData.results).length;
                        const totalServers = statusData.servers.length;
                        
                        // Safely get results and check counts
                        const currentResults = statusData.results || {};
                        const currentServers = statusData.servers || [];
                        const processedCount = Object.keys(currentResults).length;
                        const totalCount = currentServers.length;
                        
                        // Check if all servers have actually completed processing
                        // A server is considered completed if it has a status field
                        let actuallyCompletedCount = 0;
                        for (const server in currentResults) {
                            if (currentResults[server].hasOwnProperty('status')) {
                                actuallyCompletedCount++;
                            }
                        }

                        // Log current processing status with safe values
                        console.log('Processing status:', {
                            isProcessing: statusData.is_processing === true,
                            processedServers: processedCount,
                            actuallyCompletedCount: actuallyCompletedCount,
                            totalServers: totalCount,
                            results: Object.keys(currentResults),
                            servers: currentServers
                        });
                        
                        // Transition to results view when all servers are processed or when processing is stopped
                        // Also transition if there are no servers to process
                        if (statusData.is_processing === false || actuallyCompletedCount >= totalCount || totalCount === 0) {
                            logToConsole(`Transitioning to results: is_processing=${statusData.is_processing}, actually_completed=${actuallyCompletedCount}/${totalCount}`, 'info');
                            clearInterval(statusInterval);
                            clearInterval(timerInterval);
                            isProcessing = false;
                            
                            // Small delay to ensure server has finished processing
                            await new Promise(resolve => setTimeout(resolve, 200));
                            
                            // Get final results
                            try {
                                const resultsResponse = await fetch('/api/results');
                                if (resultsResponse.ok) {
                                    const resultsData = await resultsResponse.json();
                                    serverResults = resultsData.results;
                                    // Store backend start/end times (seconds -> ms) if provided
                                    processingStartTime = resultsData.start_time ? resultsData.start_time * 1000 : null;
                                    processingEndTime = resultsData.end_time ? resultsData.end_time * 1000 : null;
                                    showResults();
                                } else {
                                    logToConsole(`Failed to fetch results: ${resultsResponse.status} ${resultsResponse.statusText}`, 'error');
                                    // Still show results view even if we can't get the detailed results
                                    showResults();
                                }
                            } catch (resultsError) {
                                logToConsole(`Error fetching results: ${resultsError.message}`, 'error');
                                // Still show results view even if we can't get the detailed results
                                showResults();
                            }
                        }
                    } else {
                        // If we get an error response, stop polling and show results
                        logToConsole(`Error fetching status: ${statusResponse.status} ${statusResponse.statusText}`, 'error');
                        clearInterval(statusInterval);
                        clearInterval(timerInterval);
                        isProcessing = false;
                        showResults();
                    }
                } catch (error) {
                    logToConsole('Error polling status: ' + error.message, 'error');
                    // If there's a network error, stop polling and show results
                    clearInterval(statusInterval);
                    clearInterval(timerInterval);
                    isProcessing = false;
                    showResults();
                }
            }, 1000); // Poll every 1 second
            
        } else {
            throw new Error(data.error || 'Failed to start processing');
        }
        
    } catch (error) {
        clearInterval(timerInterval);
        logToConsole('Error during processing: ' + error.message, 'error');
        isProcessing = false;
    }
}

function updateProgressFromBackend(statusData) {
    // Update overall progress
    overallProgress.textContent = Math.round(statusData.progress) + '%';
    progressFill.style.width = statusData.progress + '%';
    
    // Safely get results and current server
    const results = statusData.results || {};
    const currentServer = statusData.current_server || null;

    // Update server items based on backend data
    servers.forEach((server, index) => {
        const serverItem = document.getElementById(`server-${index}`);
        const statusElement = document.getElementById(`status-${index}`);
        const sizeElement = document.getElementById(`size-${index}`);
        const timeElement = document.getElementById(`time-${index}`);
        
        if (!serverItem) return;
        
        // Update current server indicator with null check
        if (currentServer && currentServer === server) {
            serverItem.classList.add('processing');
        }
        
        // Update server results if available, with safe access
        const result = (statusData.results || {})[server];
        if (result && typeof result === 'object') {
            serverItem.classList.remove('processing');
            
            // Ensure status exists and is a string before comparing
            const status = (result.status || '').toString();
            if (status === 'SUCCESS') {
                serverItem.classList.add('completed');
                statusElement.textContent = 'Completed Successfully';
                
                const initialSizeGB = result.initial_size ? (result.initial_size / 1024 / 1024).toFixed(2) : 'N/A';
                const finalSizeGB = result.final_size ? (result.final_size / 1024 / 1024).toFixed(2) : 'N/A';
                sizeElement.textContent = `${initialSizeGB}GB → ${finalSizeGB}GB`;
                
                const statusSpan = serverItem.querySelector('.server-status');
                statusSpan.className = 'server-status status-completed';
                statusSpan.innerHTML = '<i class="fas fa-check"></i> Completed';
                
            } else if (result.status === 'CONNECTION_FAILED') {
                serverItem.classList.add('failed');
                statusElement.textContent = 'Connection Failed';
                
                const statusSpan = serverItem.querySelector('.server-status');
                statusSpan.className = 'server-status status-failed';
                statusSpan.innerHTML = '<i class="fas fa-wifi"></i> Connection Failed';
                
            } else if (result.status === 'FAILED' || result.status === 'ERROR') {
                serverItem.classList.add('failed');
                statusElement.textContent = 'Failed';
                
                const statusSpan = serverItem.querySelector('.server-status');
                statusSpan.className = 'server-status status-failed';
                statusSpan.innerHTML = '<i class="fas fa-times"></i> Failed';
                
            } else if (result.status === 'TIMEOUT') {
                serverItem.classList.add('failed');
                statusElement.textContent = 'Timeout';
                
                const statusSpan = serverItem.querySelector('.server-status');
                statusSpan.className = 'server-status status-failed';
                statusSpan.innerHTML = '<i class="fas fa-clock"></i> Timeout';
            }
            
            // Update duration
            if (result.duration) {
                timeElement.textContent = formatDuration(result.duration * 1000);
            }
        }
    });
    
    // Update logs
    if (statusData.logs) {
        statusData.logs.forEach(logEntry => {
            if (!document.querySelector(`[data-log-id="${logEntry.timestamp}"]`)) {
                const logLine = document.createElement('div');
                logLine.className = `console-line ${logEntry.type}`;
                logLine.textContent = `[${new Date(logEntry.timestamp).toLocaleTimeString()}] ${logEntry.message}`;
                logLine.setAttribute('data-log-id', logEntry.timestamp);
                
                consoleContent.appendChild(logLine);
            }
        });
        
        // Keep only last 100 log entries in DOM
        const logLines = consoleContent.querySelectorAll('.console-line');
        if (logLines.length > 100) {
            for (let i = 0; i < logLines.length - 100; i++) {
                logLines[i].remove();
            }
        }
        
        consoleContent.scrollTop = consoleContent.scrollHeight;
    }
}

function updateOverallProgress() {
    const progress = totalServers > 0 ? (processedServers / totalServers) * 100 : 0;
    progressFill.style.width = progress + '%';
    overallProgress.textContent = Math.round(progress) + '%';
}

function updateTimer() {
    if (startTime) {
        const elapsed = new Date() - startTime;
        elapsedTime.textContent = formatDuration(elapsed);
    }
}

function formatDuration(milliseconds) {
    const seconds = Math.floor(milliseconds / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    return `${hours.toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}

function showResults() {
    progressSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');
    
    // Calculate summary statistics
    const successful = Object.values(serverResults).filter(r => r.status === 'SUCCESS').length;
    const failed = Object.values(serverResults).filter(r => r.status !== 'SUCCESS').length;
    
    // Calculate total savings - use Excel data if available, otherwise processing results
    const totalSavings = servers.reduce((sum, server) => {
        const excelData = serverData.find(s => s.name === server);
        const result = serverResults[server] || {};
        
        if (excelData && excelData.space_saved !== null && excelData.space_saved !== undefined) {
            return sum + (excelData.space_saved || 0);
        } else if (result.initial_size && result.final_size) {
            return sum + ((result.initial_size - result.final_size) / 1024 / 1024); // Convert KB to GB
        }
        return sum;
    }, 0);
    
    // Calculate total processing time across all servers
    // Compute wall-clock total time: prefer backend start/end timestamps, else fall back to client's timer
    let totalProcessingTime = 0;
    if (processingStartTime) {
        const endMs = processingEndTime || Date.now();
        totalProcessingTime = Math.max(0, endMs - processingStartTime);
        logToConsole(`Total processing time (wall-clock) using backend timestamps: ${totalProcessingTime}ms`, 'info');
    } else if (startTime) {
        totalProcessingTime = Date.now() - startTime.getTime();
        logToConsole(`Total processing time (wall-clock) using client timer: ${totalProcessingTime}ms`, 'warning');
    } else {
        totalProcessingTime = 0;
        logToConsole('Total processing time unavailable', 'warning');
    }
    
    // Update summary cards
    document.getElementById('successCount').textContent = successful;
    document.getElementById('errorCount').textContent = failed;
    document.getElementById('totalTime').textContent = formatDuration(totalProcessingTime);
    document.getElementById('totalSavings').textContent = totalSavings.toFixed(2) + ' GB';
    
    // Populate results table
    populateResultsTable();
}

function populateResultsTable() {
    const tbody = document.getElementById('resultsTableBody');
    tbody.innerHTML = '';
    
    // Log the current state for debugging
    console.log('Populating results table:', {
        servers: servers,
        serverResults: serverResults,
        serverData: serverData
    });
    
    servers.forEach(server => {
        const result = serverResults[server] || {
            status: 'UNKNOWN',
            stopped_asyncnew_attempted: false,
            started_asyncnew_attempted: false,
            stopped_asyncnew: false,
            started_asyncnew: false
        };
        const excelData = serverData.find(s => s.name === server) || {};
        const row = document.createElement('tr');
        
        // Ensure status exists and is a string before using toLowerCase
        const statusClass = ((result.status || 'UNKNOWN').toString()).toLowerCase();
        const statusBadge = `<span class="status-badge ${statusClass}">` +
            `<i class="fas fa-${getStatusIcon(result.status)}"></i>` +
            `${result.status}` +
        `</span>`;
        
        // Use Excel data if available, otherwise use processing results
        let initialSize, finalSize, savings, reduction;
        
        if (excelData.initial_size !== null && excelData.initial_size !== undefined) {
            // Use Excel data
            initialSize = excelData.initial_size ? (excelData.initial_size.toFixed(2) + ' GB') : '-';
            finalSize = excelData.final_size ? (excelData.final_size.toFixed(2) + ' GB') : '-';
            savings = excelData.space_saved ? (excelData.space_saved.toFixed(2) + ' GB') : '-';
            reduction = excelData.reduction_percent ? (excelData.reduction_percent.toFixed(1) + '%') : '-';
        } else {
            // Use processing results
            initialSize = result.initial_size ? ((result.initial_size / 1024 / 1024).toFixed(2) + ' GB') : '-';
            finalSize = result.final_size ? ((result.final_size / 1024 / 1024).toFixed(2) + ' GB') : '-';
            
            if (result.initial_size && result.final_size) {
                const savingsKB = result.initial_size - result.final_size;
                const savingsGB = savingsKB / 1024 / 1024;
                const reductionPercent = (savingsKB / result.initial_size) * 100;
                
                savings = savingsGB.toFixed(2) + ' GB';
                reduction = reductionPercent.toFixed(1) + '%';
            } else {
                savings = '-';
                reduction = '-';
            }
        }
        
        const duration = formatDuration((result.duration || 0) * 1000);
        
        row.innerHTML = `<tr>
            <td>${server}</td>
            <td>${statusBadge}</td>
            <td>${initialSize}</td>
            <td>${finalSize}</td>
            <td>${savings}</td>
            <td>${reduction}</td>
            <td>${duration}</td>
            <td>${result.stopped_asyncnew_attempted ? (result.stopped_asyncnew ? 'Yes' : 'Attempted (Failed)') : 'No'}</td>
            <td>${result.started_asyncnew_attempted ? (result.started_asyncnew ? 'Yes' : 'Attempted (Failed)') : 'No'}</td>
        </tr>`;
        
        tbody.appendChild(row);
    });
}

function getStatusIcon(status) {
    switch (status) {
        case 'SUCCESS': return 'check';
        case 'FAILED': return 'times';
        case 'ERROR': return 'exclamation-triangle';
        case 'TIMEOUT': return 'clock';
        case 'CONNECTION_FAILED': return 'wifi';
        default: return 'question';
    }
}

// Pause and Stop functions removed as requested

function clearConsole() {
    consoleContent.innerHTML = '';
}

function logToConsole(message, type = 'info') {
    const timestamp = new Date().toLocaleTimeString();
    const logLine = document.createElement('div');
    logLine.className = `console-line ${type}`;
    logLine.textContent = `[${timestamp}] ${message}`;
    
    consoleContent.appendChild(logLine);
    consoleContent.scrollTop = consoleContent.scrollHeight;
}

function exportLogs() {
    const logs = Array.from(consoleContent.children).map(line => line.textContent).join('\n');
    const blob = new Blob([logs], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `sql-maintenance-logs-${new Date().toISOString().split('T')[0]}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function exportResults() {
    const csvData = generateCSVData();
    const blob = new Blob([csvData], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `sql-maintenance-results-${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function generateCSVData() {
    const headers = ['Server', 'Status', 'Initial Size (GB)', 'Final Size (GB)', 'Space Saved (GB)', 'Reduction %', 'Duration', 'Stopped AsyncNew', 'Started AsyncNew'];
    const rows = [headers.join(',')];
    
    servers.forEach(server => {
        const result = serverResults[server] || {};
        const excelData = serverData.find(s => s.name === server) || {};
        
        let initialSize, finalSize, savings, reduction;
        
        if (excelData.initial_size !== null && excelData.initial_size !== undefined) {
            // Use Excel data
            initialSize = excelData.initial_size ? excelData.initial_size.toFixed(2) : '-';
            finalSize = excelData.final_size ? excelData.final_size.toFixed(2) : '-';
            savings = excelData.space_saved ? excelData.space_saved.toFixed(2) : '-';
            reduction = excelData.reduction_percent ? excelData.reduction_percent.toFixed(1) : '-';
        } else {
            // Use processing results
            initialSize = result.initial_size ? (result.initial_size / 1024 / 1024).toFixed(2) : '-';
            finalSize = result.final_size ? (result.final_size / 1024 / 1024).toFixed(2) : '-';
            
            if (result.initial_size && result.final_size) {
                const savingsKB = result.initial_size - result.final_size;
                const savingsGB = savingsKB / 1024 / 1024;
                const reductionPercent = (savingsKB / result.initial_size) * 100;
                
                savings = savingsGB.toFixed(2);
                reduction = reductionPercent.toFixed(1);
            } else {
                savings = '-';
                reduction = '-';
            }
        }
        
        // Enhanced handling of AsyncNew service status
        const stoppedCol = result.stopped_asyncnew_attempted ? (result.stopped_asyncnew ? 'Yes' : 'Failed') : 'Not Attempted';
        const startedCol = result.started_asyncnew_attempted ? (result.started_asyncnew ? 'Yes' : 'Failed') : 'Not Attempted';

        const row = [
            server,
            result.status || 'UNKNOWN',
            initialSize,
            finalSize,
            savings,
            reduction,
            formatDuration((result.duration || 0) * 1000),
            stoppedCol,
            startedCol
        ];
        rows.push(row.join(','));
    });
    
    return rows.join('\n');
}

function resetToUpload() {
    // Reset all variables
    currentFile = null;
    servers = [];
    serverData = [];
    isProcessing = false;
    startTime = null;
    serverResults = {};
    processedServers = 0;
    totalServers = 0;
    
    // Reset UI
    fileInput.value = '';
    fileInfo.classList.add('hidden');
    uploadSection.classList.remove('hidden');
    progressSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    
    // Clear console
    clearConsole();
    
    // Reset progress
    progressFill.style.width = '0%';
    overallProgress.textContent = '0%';
    elapsedTime.textContent = '00:00:00';
    
    logToConsole('Ready for new processing session', 'info');
}

// Utility functions for future backend integration
async function callBackendAPI(endpoint, data) {
    try {
        const response = await fetch(`/api/${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        logToConsole(`API Error: ${error.message}`, 'error');
        throw error;
    }
}

// Example function to integrate with Python backend
async function startBackendProcessing(config, servers) {
    try {
        logToConsole('Starting backend processing...', 'info');
        
        const response = await callBackendAPI('process-servers', {
            servers: servers,
            config: config
        });
        
        logToConsole('Backend processing initiated', 'success');
        return response;
        
    } catch (error) {
        logToConsole(`Backend processing failed: ${error.message}`, 'error');
        throw error;
    }
}

// WebSocket connection for real-time updates (future implementation)
function connectWebSocket() {
    // This would be implemented for real-time updates from the Python backend
    // const ws = new WebSocket('ws://localhost:8000/ws');
    // 
    // ws.onmessage = function(event) {
    //     const data = JSON.parse(event.data);
    //     updateProgressFromBackend(data);
    // };
}

// Initialize logging
logToConsole('SQL Server Maintenance Tool initialized', 'info');
logToConsole('Ready to process server lists', 'success');
