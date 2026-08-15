package com.testsapp.controller;

import com.testsapp.dto.NotificationDispatchResponse;
import com.testsapp.dto.NotificationResponse;
import com.testsapp.service.NotificationService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.List;

@RestController
@RequestMapping("/api/notifications")
public class NotificationController {
    private final NotificationService notificationService;

    public NotificationController(NotificationService notificationService) {
        this.notificationService = notificationService;
    }

    @GetMapping
    public List<NotificationResponse> list(
            @RequestParam(required = false) String customerEmail,
            @RequestParam(required = false) Long appointmentId
    ) {
        return notificationService.listNotifications(customerEmail, appointmentId);
    }

    @PostMapping("/appointments/{appointmentId:\\d+}/reminder")
    public NotificationResponse sendReminder(@PathVariable long appointmentId) {
        return notificationService.sendReminderForAppointment(appointmentId);
    }

    @PostMapping("/reminders/dispatch")
    public NotificationDispatchResponse dispatchReminders(
            @RequestParam(required = false, defaultValue = "24") long withinHours
    ) {
        int created = notificationService.dispatchUpcomingReminders(Duration.ofHours(withinHours));
        return new NotificationDispatchResponse(created);
    }
}

