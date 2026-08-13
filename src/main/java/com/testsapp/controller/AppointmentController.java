package com.testsapp.controller;
import com.testsapp.domain.AppointmentStatus;
import com.testsapp.dto.AppointmentResponse;
import com.testsapp.dto.AvailabilitySlotResponse;
import com.testsapp.dto.CreateAppointmentRequest;
import com.testsapp.dto.DashboardResponse;
import com.testsapp.dto.RescheduleAppointmentRequest;
import com.testsapp.service.AppointmentService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import java.time.LocalDate;
import java.util.List;
@RestController
@RequestMapping("/api/appointments")
public class AppointmentController {
    private final AppointmentService appointmentService;
    public AppointmentController(AppointmentService appointmentService) {
        this.appointmentService = appointmentService;
    }
    @GetMapping
    public List<AppointmentResponse> list(
            @RequestParam(required = false) String customerEmail,
            @RequestParam(required = false) AppointmentStatus status
    ) {
        return appointmentService.listAppointments(customerEmail, status);
    }
    @GetMapping("/{id:\\d+}")
    public AppointmentResponse getById(@PathVariable long id) {
        return appointmentService.getById(id);
    }
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public AppointmentResponse create(@RequestBody CreateAppointmentRequest request) {
        return appointmentService.create(request);
    }
    @PostMapping("/{id:\\d+}/cancel")
    public AppointmentResponse cancel(@PathVariable long id) {
        return appointmentService.cancel(id);
    }
    @PostMapping("/{id:\\d+}/reschedule")
    public AppointmentResponse reschedule(@PathVariable long id, @RequestBody RescheduleAppointmentRequest request) {
        return appointmentService.reschedule(id, request);
    }
    @GetMapping("/availability")
    public List<AvailabilitySlotResponse> availability(
            @RequestParam long serviceOfferId,
            @RequestParam(required = false) LocalDate date
    ) {
        return appointmentService.availability(serviceOfferId, date);
    }
    @GetMapping("/dashboard")
    public DashboardResponse dashboard() {
        return appointmentService.dashboard();
    }
}
