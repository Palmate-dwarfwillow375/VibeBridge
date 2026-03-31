import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { IS_PLATFORM } from '../../../constants/config';
import { api } from '../../../utils/api';
import { AUTH_ERROR_MESSAGES, AUTH_TOKEN_STORAGE_KEY, AUTH_USER_ID_STORAGE_KEY } from '../constants';
import type {
  AuthContextValue,
  AuthProviderProps,
  AuthSessionPayload,
  AuthStatusPayload,
  AuthUser,
  AuthUserPayload,
  OnboardingStatusPayload,
} from '../types';
import { parseJsonSafely, resolveApiErrorMessage } from '../utils';
import { resetUserScopedStorageHydration } from '../../../utils/userScopedStorage';

const AuthContext = createContext<AuthContextValue | null>(null);
const readStoredUserId = (): string => localStorage.getItem(AUTH_USER_ID_STORAGE_KEY) || '';
const COOKIE_SESSION_TOKEN = 'cookie-session';

const persistUserId = (user: AuthUser) => {
  if (user.id === undefined || user.id === null) {
    localStorage.removeItem(AUTH_USER_ID_STORAGE_KEY);
    return;
  }

  localStorage.setItem(AUTH_USER_ID_STORAGE_KEY, String(user.id));
};

const clearStoredToken = () => {
  localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
};

const clearStoredUserId = () => {
  localStorage.removeItem(AUTH_USER_ID_STORAGE_KEY);
};

const usersMatch = (left: AuthUser | null, right: AuthUser | null): boolean => {
  if (!left || !right) {
    return left === right;
  }

  return (
    left.id === right.id &&
    left.username === right.username &&
    left.role === right.role &&
    left.nodeRegisterToken === right.nodeRegisterToken
  );
};

const hasSelectedNodeId = (): boolean => {
  try {
    return Boolean(localStorage.getItem('selectedNodeId'));
  } catch {
    return false;
  }
};

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [hasCompletedOnboarding, setHasCompletedOnboarding] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const setSession = useCallback((nextUser: AuthUser) => {
    setUser((currentUser) => (usersMatch(currentUser, nextUser) ? currentUser : nextUser));
    setToken(COOKIE_SESSION_TOKEN);
    persistUserId(nextUser);
  }, []);

  const clearSession = useCallback(() => {
    resetUserScopedStorageHydration(readStoredUserId());
    setUser(null);
    setToken(null);
    clearStoredToken();
    clearStoredUserId();
  }, []);

  const checkOnboardingStatus = useCallback(async () => {
    if (!hasSelectedNodeId()) {
      setHasCompletedOnboarding(true);
      return;
    }

    try {
      const response = await api.user.onboardingStatus();
      if (!response.ok) {
        return;
      }

      const payload = await parseJsonSafely<OnboardingStatusPayload>(response);
      setHasCompletedOnboarding(Boolean(payload?.hasCompletedOnboarding));
    } catch (caughtError) {
      console.error('Error checking onboarding status:', caughtError);
      // Fail open to avoid blocking access on transient onboarding status errors.
      setHasCompletedOnboarding(true);
    }
  }, []);

  const refreshOnboardingStatus = useCallback(async () => {
    await checkOnboardingStatus();
  }, [checkOnboardingStatus]);

  const checkAuthStatus = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      const statusResponse = await api.auth.status();
      const statusPayload = await parseJsonSafely<AuthStatusPayload>(statusResponse);

      if (statusPayload?.needsSetup) {
        setNeedsSetup(true);
        return;
      }

      setNeedsSetup(false);

      const userResponse = await api.auth.user();
      if (!userResponse.ok) {
        clearSession();
        return;
      }

      const userPayload = await parseJsonSafely<AuthUserPayload>(userResponse);
      if (!userPayload?.user) {
        clearSession();
        return;
      }

      setUser((currentUser) => (usersMatch(currentUser, userPayload.user) ? currentUser : userPayload.user));
      setToken(COOKIE_SESSION_TOKEN);
      persistUserId(userPayload.user);
    } catch (caughtError) {
      console.error('[Auth] Auth status check failed:', caughtError);
      setError(AUTH_ERROR_MESSAGES.authStatusCheckFailed);
    } finally {
      setIsLoading(false);
    }
  }, [clearSession]);

  useEffect(() => {
    if (IS_PLATFORM) {
      setUser({ username: 'platform-user' });
      setNeedsSetup(false);
      void checkOnboardingStatus().finally(() => {
        setIsLoading(false);
      });
      return;
    }

    void checkAuthStatus();
  }, [checkAuthStatus, checkOnboardingStatus]);

  const login = useCallback<AuthContextValue['login']>(
    async (username, password) => {
      try {
        setError(null);
        const response = await api.auth.login(username, password);
        const payload = await parseJsonSafely<AuthSessionPayload>(response);

        if (!response.ok || !payload?.user) {
          const message = resolveApiErrorMessage(payload, AUTH_ERROR_MESSAGES.loginFailed);
          setError(message);
          return { success: false, error: message };
        }

        setSession(payload.user);
        setNeedsSetup(false);
        return { success: true };
      } catch (caughtError) {
        console.error('Login error:', caughtError);
        setError(AUTH_ERROR_MESSAGES.networkError);
        return { success: false, error: AUTH_ERROR_MESSAGES.networkError };
      }
    },
    [setSession],
  );

  const register = useCallback<AuthContextValue['register']>(
    async (username, password) => {
      try {
        setError(null);
        const response = await api.auth.register(username, password);
        const payload = await parseJsonSafely<AuthSessionPayload>(response);

        if (!response.ok || !payload?.user) {
          const message = resolveApiErrorMessage(payload, AUTH_ERROR_MESSAGES.registrationFailed);
          setError(message);
          return { success: false, error: message };
        }

        if (!payload.pendingApproval) {
          setSession(payload.user);
          setNeedsSetup(false);
          return { success: true, message: payload.message || undefined };
        }

        setNeedsSetup(false);
        clearSession();
        return {
          success: true,
          message: payload.message || 'Registration submitted and awaiting approval.',
          pendingApproval: Boolean(payload.pendingApproval),
        };
      } catch (caughtError) {
        console.error('Registration error:', caughtError);
        setError(AUTH_ERROR_MESSAGES.networkError);
        return { success: false, error: AUTH_ERROR_MESSAGES.networkError };
      }
    },
    [clearSession, setSession],
  );

  const logout = useCallback(() => {
    clearSession();
    void api.auth.logout().catch((caughtError: unknown) => {
      console.error('Logout endpoint error:', caughtError);
    });
  }, [clearSession]);

  const contextValue = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isLoading,
      needsSetup,
      hasCompletedOnboarding,
      error,
      login,
      register,
      logout,
      refreshOnboardingStatus,
    }),
    [
      error,
      hasCompletedOnboarding,
      isLoading,
      login,
      logout,
      needsSetup,
      refreshOnboardingStatus,
      register,
      token,
      user,
    ],
  );

  return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>;
}
