import type { CredentialsRequest } from "../api/types";

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export interface RegistrationInput extends CredentialsRequest {
  passwordConfirmation: string;
}

export function validateCredentials(input: CredentialsRequest): Partial<Record<keyof CredentialsRequest, string>> {
  const errors: Partial<Record<keyof CredentialsRequest, string>> = {};
  const email = input.email.trim();

  if (!email) errors.email = "请输入邮箱。";
  else if (!emailPattern.test(email)) errors.email = "请输入有效的邮箱地址。";

  const passwordLength = Array.from(input.password).length;
  if (!input.password) errors.password = "请输入密码。";
  else if (passwordLength < 6 || passwordLength > 15) errors.password = "密码长度需要在 6 到 15 个字符之间。";

  return errors;
}

export function validateRegistration(input: RegistrationInput): Partial<Record<keyof RegistrationInput, string>> {
  const errors: Partial<Record<keyof RegistrationInput, string>> = validateCredentials(input);
  if (!input.passwordConfirmation) errors.passwordConfirmation = "请再次输入密码。";
  else if (input.password !== input.passwordConfirmation) errors.passwordConfirmation = "两次输入的密码不一致。";
  return errors;
}
