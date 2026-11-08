const screen = document.getElementById("screen");
const seed = Number(new URLSearchParams(window.location.search).get("seed") || "0");
const state = { page: "home", brightness: 40 };

document.body.dataset.seed = seed === 1 ? "shifted" : "base";

function button(label, action, className = "tile") {
  const element = document.createElement("button");
  element.className = className;
  element.type = "button";
  element.textContent = label;
  element.addEventListener("click", action);
  return element;
}

function render() {
  screen.replaceChildren();
  const header = document.createElement("header");
  const eyebrow = document.createElement("div");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "VEHICLE CONTROLS";
  const title = document.createElement("h1");
  title.textContent = state.page === "home" ? "Home" : state.page === "settings" ? "Settings" : "Display";
  header.append(eyebrow, title);
  screen.append(header);

  const panel = document.createElement("section");
  panel.className = "panel";
  if (state.page === "home") {
    const subtitle = document.createElement("p");
    subtitle.textContent = "Your cabin is ready.";
    panel.append(subtitle, button("Settings", () => { state.page = "settings"; render(); }));
  } else if (state.page === "settings") {
    const subtitle = document.createElement("p");
    subtitle.textContent = "Choose a vehicle setting.";
    panel.append(subtitle, button("Display", () => { state.page = "display"; render(); }));
  } else {
    const subtitle = document.createElement("p");
    subtitle.textContent = "Brightness";
    const value = document.createElement("div");
    value.className = "value";
    value.textContent = `${state.brightness}%`;
    const increase = button("Increase brightness", () => {
      state.brightness = Math.min(100, state.brightness + 10);
      render();
    }, "primary");
    panel.append(subtitle, value, increase, button("Return Home", () => {
      state.page = "home";
      render();
    }, "secondary"));
  }
  screen.append(panel);
}

render();
