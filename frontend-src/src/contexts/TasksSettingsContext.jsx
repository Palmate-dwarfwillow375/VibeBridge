import React, { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../utils/api';
import { useOptionalNodes } from './NodeContext';

const TasksSettingsContext = createContext({
  tasksEnabled: true,
  setTasksEnabled: () => {},
  toggleTasksEnabled: () => {},
  isTaskMasterInstalled: null,
  isTaskMasterReady: null,
  installationStatus: null,
  isCheckingInstallation: true
});

export const useTasksSettings = () => {
  const context = useContext(TasksSettingsContext);
  if (!context) {
    throw new Error('useTasksSettings must be used within a TasksSettingsProvider');
  }
  return context;
};

export const TasksSettingsProvider = ({ children }) => {
  const nodesContext = useOptionalNodes();
  const selectedNodeId = nodesContext?.selectedNodeId ?? null;
  const hasSelectableNodes = Boolean(nodesContext?.nodes?.length);
  const [tasksEnabled, setTasksEnabled] = useState(() => {
    // Load from localStorage on initialization
    const saved = localStorage.getItem('tasks-enabled');
    return saved !== null ? JSON.parse(saved) : true; // Default to true
  });
  
  const [isTaskMasterInstalled, setIsTaskMasterInstalled] = useState(null);
  const [isTaskMasterReady, setIsTaskMasterReady] = useState(null);
  const [installationStatus, setInstallationStatus] = useState(null);
  const [isCheckingInstallation, setIsCheckingInstallation] = useState(true);

  // Save to localStorage whenever tasksEnabled changes
  useEffect(() => {
    localStorage.setItem('tasks-enabled', JSON.stringify(tasksEnabled));
  }, [tasksEnabled]);

  // Check TaskMaster installation status asynchronously on component mount
  useEffect(() => {
    const checkInstallation = async () => {
      if (hasSelectableNodes && !selectedNodeId) {
        setIsTaskMasterInstalled(null);
        setIsTaskMasterReady(null);
        setInstallationStatus(null);
        setIsCheckingInstallation(false);
        return;
      }

      try {
        const response = await api.get('/taskmaster/installation-status');
        if (response.ok) {
          const data = await response.json();
          setInstallationStatus(data);
          setIsTaskMasterInstalled(data.installation?.isInstalled || false);
          setIsTaskMasterReady(data.isReady || false);
          
          // If TaskMaster is not installed and user hasn't explicitly enabled tasks,
          // disable tasks automatically
          const userEnabledTasks = localStorage.getItem('tasks-enabled');
          if (!data.installation?.isInstalled && !userEnabledTasks) {
            setTasksEnabled(false);
          }
        } else {
          console.error('Failed to check TaskMaster installation status');
          setIsTaskMasterInstalled(false);
          setIsTaskMasterReady(false);
        }
      } catch (error) {
        console.error('Error checking TaskMaster installation:', error);
        setIsTaskMasterInstalled(false);
        setIsTaskMasterReady(false);
      } finally {
        setIsCheckingInstallation(false);
      }
    };

    // Run check asynchronously without blocking initial render
    setTimeout(checkInstallation, 0);
  }, [hasSelectableNodes, selectedNodeId]);

  const toggleTasksEnabled = () => {
    setTasksEnabled(prev => !prev);
  };

  const contextValue = {
    tasksEnabled,
    setTasksEnabled,
    toggleTasksEnabled,
    isTaskMasterInstalled,
    isTaskMasterReady,
    installationStatus,
    isCheckingInstallation
  };

  return (
    <TasksSettingsContext.Provider value={contextValue}>
      {children}
    </TasksSettingsContext.Provider>
  );
};

export default TasksSettingsContext;
