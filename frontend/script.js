function showSQL()
{
let question = document.getElementById("userInput").value;

fetch("http://127.0.0.1:5000/query", {
method: "POST",
headers: {
"Content-Type": "application/json"
},
body: JSON.stringify({question: question})
})
.then(response => response.json())
.then(data => {

document.getElementById("sqlSection").style.display = "block";
document.querySelector(".query").innerText = data.sql;

window.resultData = data.data;

})
.catch(error => {
alert("Backend error");
console.log(error);
});
}

function showOutput()
{
let data = window.resultData;

if (!data || data.length === 0)
{
alert("No data found");
return;
}

let table = "<tr>";

for (let key in data[0])
{
table += `<th>${key}</th>`;
}
table += "</tr>";

data.forEach(row => {
table += "<tr>";
for (let key in row)
{
table += `<td>${row[key]}</td>`;
}
table += "</tr>";
});

document.getElementById("outputSection").style.display = "block";
document.querySelector("table").innerHTML = table;
}