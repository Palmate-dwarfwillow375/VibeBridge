import { useCallback, useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import AuthErrorAlert from './AuthErrorAlert';
import AuthInputField from './AuthInputField';
import AuthScreenLayout from './AuthScreenLayout';

type LoginFormState = {
  username: string;
  password: string;
};

const initialState: LoginFormState = {
  username: '',
  password: '',
};

export default function LoginForm() {
  const { t } = useTranslation('auth');
  const { login } = useAuth();

  const [formState, setFormState] = useState<LoginFormState>(initialState);
  const [errorMessage, setErrorMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const updateField = useCallback((field: keyof LoginFormState, value: string) => {
    setFormState((previous) => ({ ...previous, [field]: value }));
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setErrorMessage('');

      // Keep form validation local so each auth screen owns its own UI feedback.
      if (!formState.username.trim() || !formState.password) {
        setErrorMessage(t('login.errors.requiredFields'));
        return;
      }

      setIsSubmitting(true);
      const result = await login(formState.username.trim(), formState.password);
      if (!result.success) {
        setErrorMessage(result.error);
      }
      setIsSubmitting(false);
    },
    [formState.password, formState.username, login, t],
  );

  return (
    <AuthScreenLayout
      title={showRegister ? t('register.title') : t('login.title')}
      description={showRegister ? t('register.description', { defaultValue: 'Create a VibeBridge account' }) : t('login.description')}
      footerText={showRegister
        ? t('register.footer', { defaultValue: 'New accounts may require approval before full access is granted.' })
        : t('login.footer', { defaultValue: 'Enter your credentials to access VibeBridge' })}
    >
      {showRegister ? (
        <RegisterPane onBackToLogin={() => setShowRegister(false)} />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <AuthInputField
            id="username"
            label={t('login.username')}
            value={formState.username}
            onChange={(value) => updateField('username', value)}
            placeholder={t('login.placeholders.username')}
            isDisabled={isSubmitting}
          />

          <AuthInputField
            id="password"
            label={t('login.password')}
            value={formState.password}
            onChange={(value) => updateField('password', value)}
            placeholder={t('login.placeholders.password')}
            isDisabled={isSubmitting}
            type="password"
          />

          <AuthErrorAlert errorMessage={errorMessage} />

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-blue-600 px-4 py-2 font-medium text-white transition-colors duration-200 hover:bg-blue-700 disabled:bg-blue-400"
          >
            {isSubmitting ? t('login.loading') : t('login.submit')}
          </button>

          <div className="text-center text-sm text-muted-foreground">
            {t('login.noAccount', { defaultValue: "Don't have an account?" })}{' '}
            <button
              type="button"
              className="font-medium text-blue-600 hover:text-blue-700"
              onClick={() => setShowRegister(true)}
            >
              {t('login.registerLink', { defaultValue: 'Register' })}
            </button>
          </div>
        </form>
      )}
    </AuthScreenLayout>
  );
}

function RegisterPane({ onBackToLogin }: { onBackToLogin: () => void }) {
  const { t } = useTranslation('auth');
  const { register } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage('');
    setSuccessMessage('');

    if (!username.trim() || !password || !confirmPassword) {
      setErrorMessage(t('register.errors.requiredFields', { defaultValue: 'Please fill in all fields.' }));
      return;
    }
    if (username.trim().length < 3) {
      setErrorMessage(t('register.errors.usernameLength', { defaultValue: 'Username must be at least 3 characters long.' }));
      return;
    }
    if (password.length < 6) {
      setErrorMessage(t('register.errors.passwordLength', { defaultValue: 'Password must be at least 6 characters long.' }));
      return;
    }
    if (password !== confirmPassword) {
      setErrorMessage(t('register.errors.passwordMismatch', { defaultValue: 'Passwords do not match.' }));
      return;
    }

    setIsSubmitting(true);
    const result = await register(username.trim(), password);
    if (!result.success) {
      setErrorMessage(result.error);
    } else {
      setSuccessMessage(
        result.message ||
          t('register.success', { defaultValue: 'Account created successfully.' }),
      );
      if (result.pendingApproval) {
        setUsername('');
        setPassword('');
        setConfirmPassword('');
      }
    }
    setIsSubmitting(false);
  }, [confirmPassword, password, register, t, username]);

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <AuthInputField
        id="register-username"
        label={t('register.username')}
        value={username}
        onChange={setUsername}
        placeholder={t('login.placeholders.username')}
        isDisabled={isSubmitting}
      />

      <AuthInputField
        id="register-password"
        label={t('register.password')}
        value={password}
        onChange={setPassword}
        placeholder={t('login.placeholders.password')}
        isDisabled={isSubmitting}
        type="password"
      />

      <AuthInputField
        id="register-confirm-password"
        label={t('register.confirmPassword')}
        value={confirmPassword}
        onChange={setConfirmPassword}
        placeholder={t('register.placeholders.confirmPassword', { defaultValue: 'Confirm your password' })}
        isDisabled={isSubmitting}
        type="password"
      />

      <AuthErrorAlert errorMessage={errorMessage || successMessage} />

      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full rounded-md bg-blue-600 px-4 py-2 font-medium text-white transition-colors duration-200 hover:bg-blue-700 disabled:bg-blue-400"
      >
        {isSubmitting ? t('register.loading') : t('register.submit')}
      </button>

      <div className="text-center text-sm text-muted-foreground">
        {t('register.haveAccount', { defaultValue: 'Already have an account?' })}{' '}
        <button
          type="button"
          className="font-medium text-blue-600 hover:text-blue-700"
          onClick={onBackToLogin}
        >
          {t('register.signInLink', { defaultValue: 'Sign in' })}
        </button>
      </div>
    </form>
  );
}
