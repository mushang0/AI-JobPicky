import { validateCredentials, validateRegistration } from "./auth";

describe("auth validation", () => {
  it("requires a valid email and backend-compatible password length", () => {
    expect(validateCredentials({ email: "bad", password: "short" })).toEqual({
      email: "请输入有效的邮箱地址。",
      password: "密码长度需要在 15 到 128 个字符之间。",
    });
  });

  it("checks confirmation without changing the submitted password", () => {
    expect(validateRegistration({ email: "demo@example.com", password: "123456789012345", passwordConfirmation: "different" })).toEqual({
      passwordConfirmation: "两次输入的密码不一致。",
    });
  });
});
