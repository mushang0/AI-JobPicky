import { validateCredentials, validateRegistration } from "./auth";

describe("auth validation", () => {
  it("requires a valid email and backend-compatible password length", () => {
    expect(validateCredentials({ email: "bad", password: "short" })).toEqual({
      email: "请输入有效的邮箱地址。",
      password: "密码长度需要在 6 到 15 个字符之间。",
    });
  });

  it("accepts passwords from 6 through 15 characters", () => {
    expect(validateCredentials({ email: "demo@example.com", password: "12345" })).toEqual({
      password: "密码长度需要在 6 到 15 个字符之间。",
    });
    expect(validateCredentials({ email: "demo@example.com", password: "123456" })).toEqual({});
    expect(validateCredentials({ email: "demo@example.com", password: "123456789012345" })).toEqual({});
    expect(validateCredentials({ email: "demo@example.com", password: "1234567890123456" })).toEqual({
      password: "密码长度需要在 6 到 15 个字符之间。",
    });
  });

  it("checks confirmation without changing the submitted password", () => {
    expect(validateRegistration({ email: "demo@example.com", password: "123456789012345", passwordConfirmation: "different" })).toEqual({
      passwordConfirmation: "两次输入的密码不一致。",
    });
  });
});
